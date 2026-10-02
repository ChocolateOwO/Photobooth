"""Retention shapes for organizers. Counts only: never a path, a file name or a photo."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from photobooth.modules.retention.domain import (
    MetadataMode,
    RetentionPolicy,
    RetentionReport,
    RetentionRun,
)


class RetentionPolicyBody(BaseModel):
    """The booth's policy. `revision` is the one the organizer saw (a newer one refuses)."""

    model_config = ConfigDict(extra="forbid")

    originals_days: int = Field(ge=1, le=3650)
    outputs_days: int = Field(ge=1, le=3650)
    link_days: int = Field(ge=1, le=3650)
    temp_hours: int = Field(ge=1, le=720)
    metadata_mode: Literal["keep", "anonymize", "delete"]
    metadata_days: int = Field(ge=1, le=3650)
    activity_log_days: int = Field(ge=1, le=3650)
    backup_days: int = Field(ge=1, le=3650)
    app_log_days: int = Field(ge=1, le=3650)
    revision: int = Field(ge=1)

    def to_domain(self) -> RetentionPolicy:
        return RetentionPolicy(
            originals_days=self.originals_days,
            outputs_days=self.outputs_days,
            link_days=self.link_days,
            temp_hours=self.temp_hours,
            metadata_mode=MetadataMode(self.metadata_mode),
            metadata_days=self.metadata_days,
            activity_log_days=self.activity_log_days,
            backup_days=self.backup_days,
            app_log_days=self.app_log_days,
            revision=self.revision,
        )


class RetentionPolicyResponse(BaseModel):
    originals_days: int
    outputs_days: int
    link_days: int
    temp_hours: int
    metadata_mode: Literal["keep", "anonymize", "delete"]
    metadata_days: int
    activity_log_days: int
    backup_days: int
    app_log_days: int
    revision: int
    updated_at: datetime | None

    @classmethod
    def of(cls, policy: RetentionPolicy) -> RetentionPolicyResponse:
        return cls(
            originals_days=policy.originals_days,
            outputs_days=policy.outputs_days,
            link_days=policy.link_days,
            temp_hours=policy.temp_hours,
            metadata_mode=policy.metadata_mode.value,
            metadata_days=policy.metadata_days,
            activity_log_days=policy.activity_log_days,
            backup_days=policy.backup_days,
            app_log_days=policy.app_log_days,
            revision=policy.revision,
            updated_at=policy.updated_at,
        )


class RunBody(BaseModel):
    """A cleanup. Deleting needs `confirm` set to the word DELETE; a dry run needs nothing."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    confirm: str | None = Field(default=None, max_length=16)


class CountResponse(BaseModel):
    category: str
    items: int
    bytes: int


class RetentionReportResponse(BaseModel):
    dry_run: bool
    trigger: str
    started_at: datetime
    finished_at: datetime
    policy_revision: int
    counts: list[CountResponse]
    errors: list[str]

    @classmethod
    def of(cls, report: RetentionReport) -> RetentionReportResponse:
        return cls(
            dry_run=report.dry_run,
            trigger=report.trigger.value,
            started_at=report.started_at,
            finished_at=report.finished_at,
            policy_revision=report.policy_revision,
            counts=[
                CountResponse(category=c.value, items=t.items, bytes=t.bytes)
                for c, t in report.counts.items()
            ],
            errors=list(report.errors),
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
