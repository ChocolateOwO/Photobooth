"""Retention: how long the booth keeps what guests leave behind, and taking it away for good.

One policy for the booth (it runs one event at a time, and backups and logs belong to the whole
booth, not to an event). A cleanup first counts what it would delete (a dry run), and deletes
only on an explicit confirmation, or on its own schedule with the same rules. It never touches a
visit that is still going, and never a file outside this instance's own folders.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum


class RetentionError(Exception):
    """The policy or the request breaks a rule."""


class EventNotFoundError(RetentionError):
    def __init__(self) -> None:
        super().__init__("no such event")


class MetadataMode(StrEnum):
    KEEP = "keep"  # visits stay listed (no photos once they are gone)
    ANONYMIZE = "anonymize"  # after metadata_days: nothing links a visit to a device any more
    DELETE = "delete"  # after metadata_days: the visit and everything about it is deleted


class Trigger(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    STARTUP = "startup"  # before the booth opens (also right after a backup was restored)


# PROVISIONAL defaults (PLAN product defaults: originals 7 days, finished photos 30 days, link
# 7 days, temporary files 24 hours, anonymous visit data kept). The rest are chosen here.
@dataclass(frozen=True)
class RetentionPolicy:
    originals_days: int = 7
    outputs_days: int = 30
    link_days: int = 7
    temp_hours: int = 24
    metadata_mode: MetadataMode = MetadataMode.KEEP
    metadata_days: int = 90
    activity_log_days: int = 90
    backup_days: int = 7
    app_log_days: int = 14
    revision: int = 1
    updated_at: datetime | None = None

    def problems(self) -> list[str]:
        found: list[str] = []
        for name in (
            "originals_days",
            "outputs_days",
            "link_days",
            "metadata_days",
            "activity_log_days",
            "backup_days",
            "app_log_days",
        ):
            value = getattr(self, name)
            if not 1 <= value <= 3650:
                found.append(f"{name} must be 1 to 3650 days")
        if not 1 <= self.temp_hours <= 720:
            found.append("temp_hours must be 1 to 720 hours")
        if self.link_days > self.outputs_days:
            found.append("the take-home link can not outlive the finished photos")
        if self.metadata_mode is not MetadataMode.KEEP and self.metadata_days < max(
            self.originals_days, self.outputs_days
        ):
            found.append("visits can not be anonymized or deleted before their photos are")
        return found


class Category(StrEnum):
    ORIGINALS = "originals"  # the photos as the camera took them
    OUTPUTS = "outputs"  # the finished photos (their take-home links stop with them)
    VISITS_ANONYMIZED = "visits_anonymized"
    VISITS_DELETED = "visits_deleted"
    ACTIVITY = "activity"  # activity log records
    TEMP = "temp"  # unfinished temporary files
    BACKUPS = "backups"  # database backups (the newest one is always kept)
    APP_LOGS = "app_logs"  # rotated application log files (never the one being written)


@dataclass(frozen=True)
class Tally:
    items: int = 0
    bytes: int = 0


@dataclass(frozen=True)
class RetentionReport:
    """What a cleanup found (dry run) or did, per category."""

    dry_run: bool
    trigger: Trigger
    started_at: datetime
    finished_at: datetime
    policy_revision: int
    counts: Mapping[Category, Tally]
    errors: Sequence[str] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return sum(t.items for t in self.counts.values())


@dataclass(frozen=True)
class RetentionRun:
    id: str
    started_at: datetime
    finished_at: datetime
    dry_run: bool
    trigger: Trigger
    counts: Mapping[str, Mapping[str, int]]
    errors: Sequence[str]


class RetentionRepository(ABC):
    @abstractmethod
    def policy(self) -> RetentionPolicy: ...

    @abstractmethod
    def save_policy(
        self, policy: RetentionPolicy, expected_revision: int, at: datetime
    ) -> RetentionPolicy:
        """Raises RetentionError when somebody else changed it first."""

    @abstractmethod
    def add_run(self, run: RetentionRun) -> None: ...

    @abstractmethod
    def runs(self, limit: int) -> list[RetentionRun]: ...

    @abstractmethod
    def last_automatic_run(self) -> datetime | None:
        """When the last scheduled or startup cleanup (not a dry run) finished."""


def cutoff(now: datetime, days: int = 0, hours: int = 0) -> datetime:
    return now - timedelta(days=days, hours=hours)
