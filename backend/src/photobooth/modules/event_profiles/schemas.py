"""Event Profile API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from photobooth.modules.event_profiles.domain import (
    INACTIVITY_MAX_S,
    INACTIVITY_MIN_S,
    MAX_AVAILABLE_FRAMES,
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
    available_frames: list[AssetId] | None = Field(
        default=None,
        max_length=MAX_AVAILABLE_FRAMES,
        description=(
            "Frames participants may choose from, in display order (no repeats). Omit when "
            "creating a profile to offer every built-in frame."
        ),
    )
    allow_surprise_me: bool = Field(
        default=False, description="Offer a random 'Surprise me' choice (needs two frames)"
    )
    countdown_seconds: Literal[5] = 5
    mirror: bool = True
    inactivity_timeout_s: int = Field(default=120, ge=INACTIVITY_MIN_S, le=INACTIVITY_MAX_S)
    retake_mode: RetakeMode = RetakeMode.PER_PHOTO
    delivery_mode: DeliveryMode = DeliveryMode.LOCAL_LINK

    def to_domain(self, default_frames: tuple[str, ...] = ()) -> ProfileSettings:
        frames = default_frames if self.available_frames is None else tuple(self.available_frames)
        return ProfileSettings(
            name=self.name,
            title=self.title,
            subtitle=self.subtitle,
            start_button_text=self.start_button_text,
            logo_asset_id=self.logo_asset_id,
            background_asset_id=self.background_asset_id,
            theme=default_theme() if self.theme is None else self.theme.to_domain(),
            available_frames=frames,
            allow_surprise_me=self.allow_surprise_me,
            countdown_seconds=self.countdown_seconds,
            mirror=self.mirror,
            inactivity_timeout_s=self.inactivity_timeout_s,
            retake_mode=self.retake_mode,
            delivery_mode=self.delivery_mode,
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
            available_frames=list(settings.available_frames),
            allow_surprise_me=settings.allow_surprise_me,
            mirror=settings.mirror,
            inactivity_timeout_s=settings.inactivity_timeout_s,
            retake_mode=settings.retake_mode,
            delivery_mode=settings.delivery_mode,
        )


class ProfileSettingsResponse(ProfileSettingsBody):
    """Stored settings; the theme is always present."""

    theme: EventThemeBody  # narrowed: never omitted in responses
    available_frames: list[AssetId]  # narrowed: always the stored list


class ProfileUpdateBody(ProfileSettingsBody):
    revision: int = Field(ge=1, description="Revision the edit was based on (optimistic lock)")
    available_frames: list[AssetId] = Field(  # required: an edit always sends the full list
        max_length=MAX_AVAILABLE_FRAMES,
        description="Frames participants may choose from, in display order (no repeats)",
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
    available_layouts: list[LayoutKey] = Field(
        description="Layouts participants can choose: those used by an available frame"
    )

    @classmethod
    def of(cls, profile: EventProfile, layouts: list[str]) -> EventProfileResponse:
        return cls(
            id=profile.id,
            available_layouts=layouts,
            settings=ProfileSettingsResponse.of(profile.settings),
            is_active=profile.is_active,
            revision=profile.revision,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            deleted_at=profile.deleted_at,
        )


class ProblemResponse(BaseModel):
    detail: str
