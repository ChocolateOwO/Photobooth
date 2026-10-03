"""Event Profile API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from photobooth.modules.event_profiles.domain import (
    COUNTDOWN_MAX_S,
    COUNTDOWN_MIN_S,
    COUNTDOWN_SECONDS,
    INACTIVITY_MAX_S,
    INACTIVITY_MIN_S,
    MAX_LAYOUTS,
    DeliveryMode,
    EventProfile,
    ProfileSettings,
    RetakeMode,
)
from photobooth.modules.themes.domain import (
    PALETTE_MAX,
    TOKEN_KEYS,
    EventTheme,
    ThemeSource,
    default_theme,
)

Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$", examples=["#2F6FD6"])]
AssetId = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
LayoutKey = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]
TokenKey = Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]


class EventThemeBody(BaseModel):
    """Complete event theme: one colour per semantic token (every key in `tokens` is required)."""

    model_config = ConfigDict(extra="forbid")

    tokens: dict[TokenKey, Color] = Field(
        min_length=len(TOKEN_KEYS),
        max_length=len(TOKEN_KEYS),
        description="Every semantic token, e.g. background, primary_bg, primary_text, ...",
    )
    source: ThemeSource = ThemeSource.CUSTOM
    preset: str | None = Field(default=None, max_length=40)
    palette: list[Color] = Field(
        default_factory=list,
        max_length=PALETTE_MAX,
        description="Swatches extracted from the background image (source=extracted)",
    )

    def to_domain(self) -> EventTheme:
        return EventTheme(
            tokens=dict(self.tokens),
            source=self.source,
            preset=self.preset,
            palette=tuple(self.palette),
        )

    @classmethod
    def of(cls, theme: EventTheme) -> EventThemeBody:
        return cls(
            tokens=dict(theme.tokens),
            source=theme.source,
            preset=theme.preset,
            palette=list(theme.palette),
        )


class ProfileSettingsBody(BaseModel):
    """Every field an organizer can set. Unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120, description="Preparation screen title")
    subtitle: str = Field(default="", max_length=240, description="Preparation screen text")
    start_button_text: str = Field(default="Start", min_length=1, max_length=40)
    logo_asset_id: AssetId | None = None
    background_asset_id: AssetId | None = None
    theme: EventThemeBody | None = Field(
        default=None, description="Omit to use the default preset theme"
    )
    enabled_layouts: list[LayoutKey] | None = Field(
        default=None,
        max_length=MAX_LAYOUTS,
        description=(
            "Photo sizes (layout keys) participants may use; every valid frame of these sizes is "
            "offered. Omit when creating a profile to offer every size."
        ),
    )
    allow_surprise_me: bool = Field(
        default=False, description="Offer a random 'Surprise me' choice (needs two frames)"
    )
    countdown_seconds: int = Field(
        default=COUNTDOWN_SECONDS,
        ge=COUNTDOWN_MIN_S,
        le=COUNTDOWN_MAX_S,
        strict=True,
        description="Seconds counted down before each photo (whole number)",
    )
    mirror: bool = True
    inactivity_timeout_s: int = Field(default=120, ge=INACTIVITY_MIN_S, le=INACTIVITY_MAX_S)
    retake_mode: RetakeMode = RetakeMode.PER_PHOTO
    delivery_mode: DeliveryMode = DeliveryMode.LOCAL_LINK
    retention_policy_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description=(
            "The retention policy its visits keep (frozen in each visit when it starts). Omit: "
            "a new profile takes the default policy, an edit keeps its own."
        ),
    )

    def to_domain(self, default_layouts: tuple[str, ...] = ()) -> ProfileSettings:
        layouts = default_layouts if self.enabled_layouts is None else tuple(self.enabled_layouts)
        return ProfileSettings(
            name=self.name,
            title=self.title,
            subtitle=self.subtitle,
            start_button_text=self.start_button_text,
            logo_asset_id=self.logo_asset_id,
            background_asset_id=self.background_asset_id,
            theme=default_theme() if self.theme is None else self.theme.to_domain(),
            enabled_layouts=layouts,
            allow_surprise_me=self.allow_surprise_me,
            countdown_seconds=self.countdown_seconds,
            mirror=self.mirror,
            inactivity_timeout_s=self.inactivity_timeout_s,
            retake_mode=self.retake_mode,
            delivery_mode=self.delivery_mode,
            retention_policy_id=self.retention_policy_id,
        )

    @classmethod
    def of(cls, settings: ProfileSettings) -> ProfileSettingsBody:
        return cls(
            name=settings.name,
            title=settings.title,
            subtitle=settings.subtitle,
            start_button_text=settings.start_button_text,
            logo_asset_id=settings.logo_asset_id,
            background_asset_id=settings.background_asset_id,
            theme=EventThemeBody.of(settings.theme),
            enabled_layouts=list(settings.enabled_layouts),
            allow_surprise_me=settings.allow_surprise_me,
            countdown_seconds=settings.countdown_seconds,
            mirror=settings.mirror,
            inactivity_timeout_s=settings.inactivity_timeout_s,
            retake_mode=settings.retake_mode,
            delivery_mode=settings.delivery_mode,
            retention_policy_id=settings.retention_policy_id,
        )


class ProfileSettingsResponse(ProfileSettingsBody):
    """Stored settings; the theme is always present."""

    theme: EventThemeBody  # narrowed: never omitted in responses
    enabled_layouts: list[LayoutKey]  # narrowed: always the stored list
    retention_policy_id: str | None = None  # the stored policy (never omitted once 0012 ran)


class ProfileUpdateBody(ProfileSettingsBody):
    revision: int = Field(ge=1, description="Revision the edit was based on (optimistic lock)")
    enabled_layouts: list[LayoutKey] = Field(  # required: an edit always sends the full list
        max_length=MAX_LAYOUTS,
        description="Photo sizes (layout keys) participants may use",
    )


class DuplicateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)


class EventProfileResponse(BaseModel):
    id: str
    settings: ProfileSettingsResponse
    is_active: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @classmethod
    def of(cls, profile: EventProfile) -> EventProfileResponse:
        return cls(
            id=profile.id,
            settings=ProfileSettingsResponse.of(profile.settings),
            is_active=profile.is_active,
            revision=profile.revision,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            deleted_at=profile.deleted_at,
        )


class ProblemResponse(BaseModel):
    detail: str
