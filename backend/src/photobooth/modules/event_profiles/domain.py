"""Event Profile domain: validated settings, entity, repository port and lookup ports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from photobooth.modules.themes.domain import EventTheme, default_theme

COUNTDOWN_SECONDS = 5  # default for new profiles
COUNTDOWN_MIN_S = 1
COUNTDOWN_MAX_S = 10
NAME_MAX_LENGTH = 80
INACTIVITY_MIN_S = 30
INACTIVITY_MAX_S = 900
MAX_LAYOUTS = 16
NO_SIZES_FOR_ACTIVE = (
    "No photo sizes are available to participants. Choose at least one photo size before this "
    "profile can be the active event."
)
NO_FRAMES_FOR_ACTIVE = (
    "No frames exist for the chosen photo sizes. Choose another photo size or add a frame "
    "before this profile can be the active event."
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
    # Photo sizes (layout keys) participants may use. Every valid frame of these layouts is
    # offered at the booth, including frames uploaded later; the participant's chosen frame
    # decides the capture count and the outputs.
    enabled_layouts: tuple[str, ...] = field(default=())
    # Offer a "Surprise me" card (random choice among the offered frames; needs two or more).
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
        if len(set(self.enabled_layouts)) != len(self.enabled_layouts):
            found.append("a photo size can be chosen only once")
        if len(self.enabled_layouts) > MAX_LAYOUTS:
            found.append(f"at most {MAX_LAYOUTS} photo sizes can be chosen")
        countdown = self.countdown_seconds
        if (
            isinstance(countdown, bool)
            or not isinstance(countdown, int)
            or not COUNTDOWN_MIN_S <= countdown <= COUNTDOWN_MAX_S
        ):
            found.append(
                f"countdown_seconds must be a whole number from {COUNTDOWN_MIN_S} to "
                f"{COUNTDOWN_MAX_S}"
            )
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
    def remove_deleted(self, profile_id: str) -> bool:
        """Delete a profile that is already deleted (soft) for good; False when it is not one.
        Its visits must be gone first (the database refuses otherwise)."""

    @abstractmethod
    def names_by_layout(self) -> dict[str, list[str]]:
        """layout key -> names of the profiles offering it (soft-deleted ones marked)."""


class AssetLookup(Protocol):
    def exists(self, asset_id: str, kind: str) -> bool: ...


class FrameLookup(Protocol):
    """How many valid frames exist for these layouts (frames module)."""

    def valid_frame_count(self, layouts: Sequence[str]) -> int: ...


class HasKey(Protocol):
    @property
    def key(self) -> str: ...


class TemplateCatalog(Protocol):
    def list_latest(self) -> Sequence[HasKey]: ...
