"""Retention shapes for organizers. Counts only: never a path, a file name or a photo."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from photobooth.modules.retention.domain import (
    DAYS_MAX,
    POLICY_NAME_MAX,
    Housekeeping,
    MetadataMode,
    RetentionPolicy,
    RetentionReport,
    RetentionRun,
)

Days = Field(ge=1, le=DAYS_MAX)


class RetentionPolicyBody(BaseModel):
    """A named policy an Event Profile can select. On a change, `revision` is the one the
    organizer saw (a newer one refuses)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=POLICY_NAME_MAX)
    originals_days: int = Days
    outputs_days: int = Days
    link_days: int = Days
    metadata_mode: Literal["keep", "anonymize", "delete"]
    metadata_days: int = Days
    revision: int = Field(default=1, ge=1)

    def to_domain(self) -> RetentionPolicy:
        return RetentionPolicy(
            name=self.name,
            originals_days=self.originals_days,
            outputs_days=self.outputs_days,
            link_days=self.link_days,
            metadata_mode=MetadataMode(self.metadata_mode),
            metadata_days=self.metadata_days,
            revision=self.revision,
        )


class RetentionPolicyResponse(BaseModel):
    id: str
    name: str
    originals_days: int
    outputs_days: int
    link_days: int
    metadata_mode: Literal["keep", "anonymize", "delete"]
    metadata_days: int
    is_default: bool
    revision: int
    updated_at: datetime | None
    used_by: int = Field(description="Event Profiles selecting it, deleted ones included.")

    @classmethod
    def of(cls, policy: RetentionPolicy, used_by: int) -> RetentionPolicyResponse:
        return cls(
            id=policy.id,
            name=policy.name,
            originals_days=policy.originals_days,
            outputs_days=policy.outputs_days,
            link_days=policy.link_days,
            metadata_mode=policy.metadata_mode.value,
            metadata_days=policy.metadata_days,
            is_default=policy.is_default,
            revision=policy.revision,
            updated_at=policy.updated_at,
            used_by=used_by,
        )


class HousekeepingBody(BaseModel):
    """What belongs to the whole booth. `revision` is the one the organizer saw."""

    model_config = ConfigDict(extra="forbid")

    temp_hours: int = Field(ge=1, le=720)
    activity_log_days: int = Days
    backup_days: int = Days
    app_log_days: int = Days
    revision: int = Field(ge=1)

    def to_domain(self) -> Housekeeping:
        return Housekeeping(
            temp_hours=self.temp_hours,
            activity_log_days=self.activity_log_days,
            backup_days=self.backup_days,
            app_log_days=self.app_log_days,
            revision=self.revision,
        )


class HousekeepingResponse(BaseModel):
    temp_hours: int
    activity_log_days: int
    backup_days: int
    app_log_days: int
    revision: int
    updated_at: datetime | None

    @classmethod
    def of(cls, housekeeping: Housekeeping) -> HousekeepingResponse:
        return cls(
            temp_hours=housekeeping.temp_hours,
            activity_log_days=housekeeping.activity_log_days,
            backup_days=housekeeping.backup_days,
            app_log_days=housekeeping.app_log_days,
            revision=housekeeping.revision,
            updated_at=housekeeping.updated_at,
        )


class RunBody(BaseModel):
    """A cleanup. Deleting needs `confirm` set to the word DELETE; a dry run needs nothing."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    confirm: str | None = Field(default=None, max_length=16)
    housekeeping_revision: int | None = Field(
        default=None,
        ge=1,
        description="The housekeeping settings the dry run showed; required to delete.",
    )


class RemoveBody(BaseModel):
    """Deleting an event for good: a dry run first, then DELETE to confirm."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    confirm: str | None = Field(default=None, max_length=16)


class CountResponse(BaseModel):
    category: str
    items: int
    bytes: int
    failed: int = Field(default=0, description="Found but not deleted; tried again next time.")


class RetentionReportResponse(BaseModel):
    dry_run: bool
    trigger: str
    started_at: datetime
    finished_at: datetime
    housekeeping_revision: int
    counts: list[CountResponse]
    errors: list[str]
    complete: bool = Field(description="Every category ran and every file found could go.")

    @classmethod
    def of(cls, report: RetentionReport) -> RetentionReportResponse:
        return cls(
            dry_run=report.dry_run,
            trigger=report.trigger.value,
            started_at=report.started_at,
            finished_at=report.finished_at,
            housekeeping_revision=report.housekeeping_revision,
            counts=[
                CountResponse(category=c.value, items=t.items, bytes=t.bytes, failed=t.failed)
                for c, t in report.counts.items()
            ],
            errors=list(report.errors),
            complete=not report.errors,
        )


class RetentionRunResponse(BaseModel):
    id: str
    started_at: datetime
    finished_at: datetime
    dry_run: bool
    trigger: str
    counts: list[CountResponse]
    errors: list[str]

    @classmethod
    def of(cls, run: RetentionRun) -> RetentionRunResponse:
        return cls(
            id=run.id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            dry_run=run.dry_run,
            trigger=run.trigger.value,
            counts=[
                CountResponse(
                    category=category,
                    items=int(tally.get("items", 0)),
                    bytes=int(tally.get("bytes", 0)),
                    failed=int(tally.get("failed", 0)),
                )
                for category, tally in run.counts.items()
            ],
            errors=list(run.errors),
        )


class EventRemovalResponse(BaseModel):
    """What deleting an event for good takes (dry run) or took with it."""

    dry_run: bool
    visits: int
    bytes: int
