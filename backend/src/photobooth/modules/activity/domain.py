"""Activity: what happened at the booth and in Admin, kept as small, privacy-safe records.

An activity record names its type, when it happened, who caused it (the booth, a guest's phone,
an organizer or the system), the visit and event it belongs to, and a payload of a few allowlisted
facts. It never holds a delivery token, a password, a file path, an IP address, image data or
free text typed by anybody: each type lists the payload keys it may carry, every value is a short
plain word or number, and anything else is dropped before it is stored.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Actor(StrEnum):
    BOOTH = "booth"  # the kiosk screen a guest uses
    GUEST = "guest"  # a guest's phone on the take-home link
    ADMIN = "admin"  # an organizer signed in to Admin
    SYSTEM = "system"  # the app itself (timeouts, recovery, upkeep)


class ActivityType(StrEnum):
    # A guest's visit, from the booth screen.
    SESSION_STARTED = "session_started"
    FRAME_CHOSEN = "frame_chosen"
    CAPTURE_OK = "capture_ok"
    CAPTURE_FAILED = "capture_failed"
    RETAKE = "retake"
    PHOTOS_CONFIRMED = "photos_confirmed"
    RENDER_OK = "render_ok"
    RENDER_FAILED = "render_failed"
    LINK_SHOWN = "link_shown"
    SESSION_ENDED = "session_ended"
    RESET_TIMEOUT = "reset_timeout"
    # The take-home link, from a guest's phone.
    QR_OPENED = "qr_opened"
    DOWNLOAD = "download"
    # Organizers in Admin.
    ADMIN_LOGIN = "admin_login"
    ADMIN_LOGIN_FAILED = "admin_login_failed"
    ADMIN_LOGOUT = "admin_logout"
    ADMIN_PROFILE_CREATED = "admin_profile_created"
    ADMIN_PROFILE_UPDATED = "admin_profile_updated"
    ADMIN_PROFILE_DUPLICATED = "admin_profile_duplicated"
    ADMIN_PROFILE_ACTIVATED = "admin_profile_activated"
    ADMIN_PROFILE_DELETED = "admin_profile_deleted"
    ADMIN_PROFILE_RESTORED = "admin_profile_restored"
    ADMIN_FRAME_UPLOADED = "admin_frame_uploaded"
    ADMIN_FRAME_REPLACED = "admin_frame_replaced"
    ADMIN_FRAME_RENAMED = "admin_frame_renamed"
    ADMIN_FRAME_DELETED = "admin_frame_deleted"
    ADMIN_ASSET_UPLOADED = "admin_asset_uploaded"
    ADMIN_ASSET_DELETED = "admin_asset_deleted"
    ADMIN_TEST_STARTED = "admin_test_started"
    ADMIN_TESTS_CLEARED = "admin_tests_cleared"


# The only payload keys each type may carry. Values are short words or numbers (see `clean`).
PAYLOAD_KEYS: Mapping[ActivityType, frozenset[str]] = {
    ActivityType.SESSION_STARTED: frozenset(),
    ActivityType.FRAME_CHOSEN: frozenset({"layout", "captures", "outputs"}),
    ActivityType.CAPTURE_OK: frozenset({"shot", "attempt"}),
    ActivityType.CAPTURE_FAILED: frozenset({"shot", "attempt", "reason"}),
    ActivityType.RETAKE: frozenset({"shots"}),
    ActivityType.PHOTOS_CONFIRMED: frozenset({"photos"}),
    ActivityType.RENDER_OK: frozenset({"outputs", "filter", "stickers"}),
    ActivityType.RENDER_FAILED: frozenset({"reason"}),
    ActivityType.LINK_SHOWN: frozenset({"renewed"}),
    ActivityType.SESSION_ENDED: frozenset({"state", "reason"}),
    ActivityType.RESET_TIMEOUT: frozenset({"state"}),
    ActivityType.QR_OPENED: frozenset(),
    ActivityType.DOWNLOAD: frozenset({"kind", "output"}),
    ActivityType.ADMIN_LOGIN: frozenset(),
    ActivityType.ADMIN_LOGIN_FAILED: frozenset({"reason"}),
    ActivityType.ADMIN_LOGOUT: frozenset(),
    ActivityType.ADMIN_PROFILE_CREATED: frozenset({"target"}),
    ActivityType.ADMIN_PROFILE_UPDATED: frozenset({"target"}),
    ActivityType.ADMIN_PROFILE_DUPLICATED: frozenset({"target"}),
    ActivityType.ADMIN_PROFILE_ACTIVATED: frozenset({"target"}),
    ActivityType.ADMIN_PROFILE_DELETED: frozenset({"target"}),
    ActivityType.ADMIN_PROFILE_RESTORED: frozenset({"target"}),
    ActivityType.ADMIN_FRAME_UPLOADED: frozenset({"target"}),
    ActivityType.ADMIN_FRAME_REPLACED: frozenset({"target"}),
    ActivityType.ADMIN_FRAME_RENAMED: frozenset({"target"}),
    ActivityType.ADMIN_FRAME_DELETED: frozenset({"target"}),
    ActivityType.ADMIN_ASSET_UPLOADED: frozenset({"target"}),
    ActivityType.ADMIN_ASSET_DELETED: frozenset({"target"}),
    ActivityType.ADMIN_TEST_STARTED: frozenset({"target"}),
    ActivityType.ADMIN_TESTS_CLEARED: frozenset(),
}

ACTOR_OF: Mapping[ActivityType, Actor] = {
    **{t: Actor.BOOTH for t in ActivityType if not t.value.startswith(("admin_", "qr_"))},
    ActivityType.DOWNLOAD: Actor.GUEST,
    ActivityType.QR_OPENED: Actor.GUEST,
    ActivityType.RESET_TIMEOUT: Actor.SYSTEM,
    **{t: Actor.ADMIN for t in ActivityType if t.value.startswith("admin_")},
}

PayloadValue = str | int | bool
Payload = Mapping[str, PayloadValue]

# A short lowercase code word: a reason, a layout key, a filter name. A take-home token (43
# mixed-case characters) can never match, nor can a path, an address or text anybody typed.
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_STATES = frozenset(
    {
        "eligibility_ok",
        "capturing",
        "reviewing",
        "delivered",
        "completed",
        "cancelled",
        "abandoned",
        "error",
    }
)


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000


def _flag(value: object) -> bool:
    return isinstance(value, bool)


def _code(value: object) -> bool:
    return isinstance(value, str) and bool(_CODE.match(value))


# The schema of every payload field (P10-R4): what each value may be, and nothing else.
FIELD_RULES: Mapping[str, Callable[[object], bool]] = {
    "shot": _count,
    "attempt": _count,
    "captures": _count,
    "outputs": _count,
    "photos": _count,
    "shots": _count,
    "stickers": _count,
    "output": _count,
    "renewed": _flag,
    "reason": _code,
    "layout": _code,
    "filter": _code,
    "state": lambda value: value in _STATES,
    "kind": lambda value: value in {"file", "zip"},
    "target": lambda value: isinstance(value, str) and bool(_UUID.match(value)),
}


def clean(kind: ActivityType, payload: Mapping[str, object]) -> dict[str, PayloadValue]:
    """Only the keys this type allows, each only in the shape its field allows."""
    allowed = PAYLOAD_KEYS[kind]
    kept: dict[str, PayloadValue] = {}
    for key, value in payload.items():
        rule = FIELD_RULES.get(key)
        if key in allowed and rule is not None and rule(value):
            kept[key] = value  # type: ignore[assignment]  # the rule checked the type
    return kept


@dataclass(frozen=True)
class ActivityRecord:
    id: str
    at: datetime
    type: ActivityType
    actor: Actor
    session_id: str | None = None
    profile_id: str | None = None
    admin_username: str | None = None
    payload: Mapping[str, PayloadValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ActivityFilter:
    types: Sequence[ActivityType] = ()
    actors: Sequence[Actor] = ()
    session_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class ActivityRepository(ABC):
    @abstractmethod
    def add(self, record: ActivityRecord) -> None: ...

    @abstractmethod
    def search(
        self, where: ActivityFilter, limit: int, before: tuple[datetime, str] | None = None
    ) -> list[ActivityRecord]:
        """Newest first; `before` continues a previous page (its last record's at and id)."""

    @abstractmethod
    def for_session(self, session_id: str) -> list[ActivityRecord]:
        """Oldest first: a visit's own timeline."""

    @abstractmethod
    def purge(self, before: datetime, dry_run: bool) -> int:
        """Records older than `before`: counted, and deleted unless this is a dry run."""
