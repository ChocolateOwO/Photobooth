"""Activity, history and statistics as Admin sees them. No token, path, IP or photo appears."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from photobooth.modules.activity.domain import ActivityRecord
from photobooth.modules.activity.service import Statistics, VisitDetail, VisitView


class ActivityRecordResponse(BaseModel):
    id: str
    at: datetime
    type: str = Field(examples=["capture_ok"])
    actor: str = Field(examples=["booth"], description="booth, guest, admin or system")
    session_id: str | None
    profile_id: str | None
    admin_username: str | None
    payload: dict[str, str | int | bool]

    @classmethod
    def of(cls, record: ActivityRecord) -> ActivityRecordResponse:
        return cls(
            id=record.id,
            at=record.at,
            type=record.type.value,
            actor=record.actor.value,
            session_id=record.session_id,
            profile_id=record.profile_id,
            admin_username=record.admin_username,
            payload=dict(record.payload),
        )


class ActivityPage(BaseModel):
    records: list[ActivityRecordResponse]
    more: bool = Field(description="Older records follow; ask again with before_at/before_id.")


class VisitResponse(BaseModel):
    """One guest's visit (never an organizer's test)."""

    id: str
    started_at: datetime
    ended_at: datetime | None
    state: str
    end_reason: str | None
    profile_id: str
    profile_name: str | None
    layout: str | None
    photos: int
    retakes: int
    failed_attempts: int
    outputs: int
    filter: str | None
    stickers: int
    link_issued: bool
    link_opened: bool
    downloads: int

    @classmethod
    def of(cls, view: VisitView) -> VisitResponse:
        v = view.visit
        return cls(
            id=v.id,
            started_at=v.started_at,
            ended_at=v.ended_at,
            state=v.state,
            end_reason=v.end_reason,
            profile_id=v.profile_id,
            profile_name=view.profile_name,
            layout=v.layout,
            photos=v.photos,
            retakes=v.retakes,
            failed_attempts=v.failed_attempts,
            outputs=v.outputs,
            filter=v.filter,
            stickers=v.stickers,
            link_issued=view.link.issued,
            link_opened=view.link.opened,
            downloads=view.link.downloads,
        )


class HistoryPage(BaseModel):
    visits: list[VisitResponse]
    total: int
    offset: int


class VisitDetailResponse(BaseModel):
    visit: VisitResponse
    timeline: list[ActivityRecordResponse]

    @classmethod
    def of(cls, detail: VisitDetail) -> VisitDetailResponse:
        return cls(
            visit=VisitResponse.of(detail.view),
            timeline=[ActivityRecordResponse.of(r) for r in detail.timeline],
        )


class CountResponse(BaseModel):
    key: str
    count: int


class StatisticsResponse(BaseModel):
    since: datetime | None
    until: datetime | None
    visits: int = Field(description="Guests' visits started (organizer tests never count).")
    finished: int = Field(description="Visits whose finished photos were made.")
    cancelled: int
    abandoned: int
    errors: int
    in_progress: int
    photos: int
    retakes: int
    failed_attempts: int
    outputs: int
    decorated: int = Field(description="Finished visits with a filter or stickers.")
    links_opened: int
    downloads: int
    average_minutes: float | None = Field(description="Start to finish, finished visits only.")
    by_layout: list[CountResponse]
    by_hour: list[CountResponse] = Field(description="Visits started per hour (booth clock).")
    by_filter: list[CountResponse]

    @classmethod
    def of(cls, stats: Statistics) -> StatisticsResponse:
        return cls(
            since=stats.since,
            until=stats.until,
            visits=stats.visits,
            finished=stats.finished,
            cancelled=stats.cancelled,
            abandoned=stats.abandoned,
            errors=stats.errors,
            in_progress=stats.in_progress,
            photos=stats.photos,
            retakes=stats.retakes,
            failed_attempts=stats.failed_attempts,
            outputs=stats.outputs,
            decorated=stats.decorated,
            links_opened=stats.links_opened,
            downloads=stats.downloads,
            average_minutes=stats.average_minutes,
            by_layout=[CountResponse(key=k, count=c) for k, c in stats.by_layout.items()],
            by_hour=[CountResponse(key=f"{h:02d}", count=c) for h, c in stats.by_hour.items()],
            by_filter=[CountResponse(key=k, count=c) for k, c in stats.by_filter.items()],
        )
