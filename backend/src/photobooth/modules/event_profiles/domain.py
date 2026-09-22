"""Event Profile domain: validated settings, entity, repository port and lookup ports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from photobooth.modules.themes.domain import EventTheme, default_theme

COUNTDOWN_SECONDS = 5  # fixed in the MVP (plan: countdown locked to 5 s)
NAME_MAX_LENGTH = 80
INACTIVITY_MIN_S = 30
INACTIVITY_MAX_S = 900
MAX_AVAILABLE_FRAMES = 200
NO_FRAMES_FOR_ACTIVE = (
    "No frames are available to participants. Enable at least one frame before this profile "
    "can be the active event."
)


class RetakeMode(StrEnum):
    NONE = "none"
    PER_PHOTO = "per_photo"
    ALL = "all"


class DeliveryMode(StrEnum):
    LOCAL_LINK = "local_link"  # confirmed: LAN-only QR delivery in the MVP


class ProfileError(Exception):
    """Base error for Event Profile operations."""


class ProfileValidationError(ProfileError):
    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


class ProfileNotFoundError(ProfileError):
    def __init__(self, profile_id: str) -> None:
        super().__init__(f"event profile not found: {profile_id}")


class ProfileConflictError(ProfileError):
    """Stale revision, duplicate name, or an operation not allowed in the current state."""


@dataclass(frozen=True)
class ProfileSettings:
    name: str
    title: str
    subtitle: str = ""
    start_button_text: str = "Start"
    logo_asset_id: str | None = None
    background_asset_id: str | None = None
    # Complete semantic colour set for every event-facing element (see themes.domain).
    theme: EventTheme = field(default_factory=default_theme)
    # Frames participants may choose from, in the order they are shown. A layout is offered to
    # participants exactly when at least one of these frames uses it; the participant's chosen
    # frame decides the capture count and the outputs.
    available_frames: tuple[str, ...] = field(default=())
    # Offer a "Surprise me" card (random choice among the available frames; needs two or more).
    allow_surprise_me: bool = False
    countdown_seconds: int = COUNTDOWN_SECONDS
    mirror: bool = True
    inactivity_timeout_s: int = 120
    retake_mode: RetakeMode = RetakeMode.PER_PHOTO
    delivery_mode: DeliveryMode = DeliveryMode.LOCAL_LINK

    @property
    def name_key(self) -> str:
        """Case-insensitive uniqueness key."""
        return " ".join(self.name.split()).casefold()

    def problems(self) -> list[str]:
        found: list[str] = []
        for label, value, low, high in (
            ("name", self.name, 1, NAME_MAX_LENGTH),
            ("title", self.title, 1, 120),
            ("subtitle", self.subtitle, 0, 240),
            ("start_button_text", self.start_button_text, 1, 40),
        ):
            stripped = value.strip()
            if not low <= len(stripped) <= high:
                found.append(f"{label} must be {low}-{high} characters")
            if any(ord(ch) < 32 for ch in value):
                found.append(f"{label} must not contain control characters")
        found.extend(self.theme.problems())
        if len(set(self.available_frames)) != len(self.available_frames):
            found.append("a frame can be made available only once")
        if len(self.available_frames) > MAX_AVAILABLE_FRAMES:
            found.append(f"at most {MAX_AVAILABLE_FRAMES} frames can be made available")
        if self.countdown_seconds != COUNTDOWN_SECONDS:
            found.append(f"countdown_seconds is fixed at {COUNTDOWN_SECONDS}")
        if not INACTIVITY_MIN_S <= self.inactivity_timeout_s <= INACTIVITY_MAX_S:
            found.append(
                f"inactivity_timeout_s must be {INACTIVITY_MIN_S}-{INACTIVITY_MAX_S} seconds"
            )
        return found


@dataclass(frozen=True)
class EventProfile:
    id: str
    settings: ProfileSettings
    is_active: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None


class EventProfileRepository(ABC):
    @abstractmethod
    def list_profiles(self, include_deleted: bool) -> list[EventProfile]: ...

    @abstractmethod
    def get(self, profile_id: str) -> EventProfile | None: ...

    @abstractmethod
    def get_active(self) -> EventProfile | None: ...

    @abstractmethod
    def add(self, profile: EventProfile) -> EventProfile:
        """Raise ProfileConflictError when the name is already used by a live profile."""

    @abstractmethod
    def update(
        self, profile_id: str, settings: ProfileSettings, expected_revision: int, at: datetime
    ) -> EventProfile:
        """Replace settings when `expected_revision` matches; bump revision."""

    @abstractmethod
    def activate(self, profile_id: str, at: datetime) -> EventProfile:
        """Atomically make this live profile the only active one."""

    @abstractmethod
    def soft_delete(
        self, profile_id: str, expected_revision: int, at: datetime
    ) -> EventProfile: ...

    @abstractmethod
    def restore(self, profile_id: str, at: datetime) -> EventProfile: ...

    @abstractmethod
    def names_using_frame(self, frame_id: str) -> list[str]:
        """Names of profiles offering this frame, including soft-deleted ones (restorable)."""

    @abstractmethod
    def usage_by_frame(self) -> dict[str, list[str]]:
        """frame id -> names of the profiles offering it (soft-deleted ones marked)."""


class AssetLookup(Protocol):
    def exists(self, asset_id: str, kind: str) -> bool: ...


class FrameLookup(Protocol):
    """The layout a frame belongs to, or None when the frame does not exist (frames module)."""

    def frame_template(self, frame_id: str) -> str | None: ...

    def builtin_frame_ids(self) -> list[str]:
        """Every built-in frame, in library order (the default for a new profile)."""
        ...


class HasKey(Protocol):
    @property
    def key(self) -> str: ...


class TemplateCatalog(Protocol):
    def list_latest(self) -> Sequence[HasKey]: ...
