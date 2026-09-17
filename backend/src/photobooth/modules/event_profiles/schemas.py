"""Event Profile API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from photobooth.modules.event_profiles.domain import (
    INACTIVITY_MAX_S,
    INACTIVITY_MIN_S,
    DeliveryMode,
    EventProfile,
    ProfileSettings,
    RetakeMode,
)

Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$", examples=["#2F6FD6"])]
AssetId = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
LayoutKey = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]


class ProfileSettingsBody(BaseModel):
    """Every field an organizer can set. Unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120, description="Preparation screen title")
    subtitle: str = Field(default="", max_length=240, description="Preparation screen text")
    start_button_text: str = Field(default="Start", min_length=1, max_length=40)
    logo_asset_id: AssetId | None = None
    background_asset_id: AssetId | None = None
    background_color: Color = "#101418"
    primary_color: Color = "#2F6FD6"
    secondary_color: Color = "#FFB020"
    button_color: Color = "#2F6FD6"
    text_color: Color = "#F4F6F8"
    enabled_layouts: list[LayoutKey] = Field(min_length=1, max_length=16)
    # Chosen frame per layout; a layout may be missing here, which means "no frame selected".
    frame_selections: dict[LayoutKey, AssetId] = Field(default_factory=dict, max_length=16)
    countdown_seconds: Literal[5] = 5
    mirror: bool = True
    inactivity_timeout_s: int = Field(default=120, ge=INACTIVITY_MIN_S, le=INACTIVITY_MAX_S)
    retake_mode: RetakeMode = RetakeMode.PER_PHOTO
    delivery_mode: DeliveryMode = DeliveryMode.LOCAL_LINK

    def to_domain(self) -> ProfileSettings:
        return ProfileSettings(
            name=self.name,
            title=self.title,
            subtitle=self.subtitle,
            start_button_text=self.start_button_text,
            logo_asset_id=self.logo_asset_id,
            background_asset_id=self.background_asset_id,
            background_color=self.background_color,
            primary_color=self.primary_color,
            secondary_color=self.secondary_color,
            button_color=self.button_color,
            text_color=self.text_color,
            enabled_layouts=tuple(self.enabled_layouts),
            frame_selections=tuple(sorted(self.frame_selections.items())),
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
            background_color=settings.background_color,
            primary_color=settings.primary_color,
            secondary_color=settings.secondary_color,
            button_color=settings.button_color,
            text_color=settings.text_color,
            enabled_layouts=list(settings.enabled_layouts),
            frame_selections=dict(settings.frame_selections),
            mirror=settings.mirror,
            inactivity_timeout_s=settings.inactivity_timeout_s,
            retake_mode=settings.retake_mode,
            delivery_mode=settings.delivery_mode,
        )


class ProfileUpdateBody(ProfileSettingsBody):
    revision: int = Field(ge=1, description="Revision the edit was based on (optimistic lock)")


class DuplicateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)


class EventProfileResponse(BaseModel):
    id: str
    settings: ProfileSettingsBody
    is_active: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @classmethod
    def of(cls, profile: EventProfile) -> EventProfileResponse:
        return cls(
            id=profile.id,
            settings=ProfileSettingsBody.of(profile.settings),
            is_active=profile.is_active,
            revision=profile.revision,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            deleted_at=profile.deleted_at,
        )


class ProblemResponse(BaseModel):
    detail: str
