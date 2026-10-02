"""Activity use cases: record what happened, read it back, and count it for the organizer."""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from photobooth.modules.activity.domain import (
    ACTOR_OF,
    ActivityFilter,
    ActivityRecord,
    ActivityRepository,
    ActivityType,
    clean,
)

logger = logging.getLogger(__name__)

# Visit states as the sessions module names them (plain words: no import of that module).
FINISHED = frozenset({"delivered", "completed"})
ENDED_EARLY = frozenset({"cancelled", "abandoned", "error"})


@dataclass(frozen=True)
class Visit:
    """One guest's visit as History and Statistics see it. Never a test visit."""

    id: str
    started_at: datetime
    ended_at: datetime | None
    photos_made_at: datetime | None
    state: str
    end_reason: str | None
    profile_id: str
    layout: str | None
    photos: int
    failed_attempts: int
    retakes: int
    outputs: int
    filter: str | None
    stickers: int


@dataclass(frozen=True)
class LinkFacts:
    """The take-home link of one visit, summed over every link it was given."""

    issued: bool
    opened: bool
    downloads: int


@dataclass(frozen=True)
class VisitFilter:
    since: datetime | None = None
    until: datetime | None = None
    profile_id: str | None = None
    states: Sequence[str] = ()


class VisitSource(Protocol):
    """Guests' visits (the sessions module): newest first, never test visits."""

    def visits(self, where: VisitFilter) -> list[Visit]: ...

    def visit(self, session_id: str) -> Visit | None: ...


class LinkSource(Protocol):
    """What happened to the take-home links (the delivery module). No token, ever."""

    def facts(self, session_ids: Sequence[str]) -> Mapping[str, LinkFacts]: ...


class ProfileNames(Protocol):
    def names(self) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class VisitView:
    visit: Visit
    link: LinkFacts
    profile_name: str | None


@dataclass(frozen=True)
class VisitDetail:
    view: VisitView
    timeline: tuple[ActivityRecord, ...]


@dataclass(frozen=True)
class Statistics:
    since: datetime | None
    until: datetime | None
    visits: int
    finished: int
    cancelled: int
    abandoned: int
    errors: int
    in_progress: int
    photos: int
    retakes: int
    failed_attempts: int
    outputs: int
    decorated: int
    links_opened: int
    downloads: int
    average_minutes: float | None
    by_layout: Mapping[str, int] = field(default_factory=dict)
    by_hour: Mapping[int, int] = field(default_factory=dict)
    by_filter: Mapping[str, int] = field(default_factory=dict)


class ActivityService:
    def __init__(
        self,
        repository: ActivityRepository,
        visits: VisitSource,
        links: LinkSource,
        profiles: ProfileNames,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._visits = visits
        self._links = links
        self._profiles = profiles
        self._clock = clock or (lambda: datetime.now(UTC))

    # ---- recording ---------------------------------------------------------------------------

    def record(
        self,
        kind: ActivityType,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        admin_username: str | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        """Keep one record. Never raises: the guest's visit or the organizer's change has already
        happened, and a record that can not be kept is reported (type only) and skipped."""
        try:
            self._repository.add(
                ActivityRecord(
                    id=str(uuid.uuid4()),
                    at=self._clock(),
                    type=kind,
                    actor=ACTOR_OF[kind],
                    session_id=session_id,
                    profile_id=profile_id,
                    admin_username=admin_username,
                    payload=clean(kind, payload or {}),
                )
            )
        except Exception as exc:
            logger.warning("activity record %s not kept (%s)", kind.value, type(exc).__name__)

    # ---- reading -----------------------------------------------------------------------------

    def search(
        self, where: ActivityFilter, limit: int = 50, before: tuple[datetime, str] | None = None
    ) -> list[ActivityRecord]:
        # Up to 200 a page, plus one to tell whether another page follows (P10-R5).
        return self._repository.search(where, max(1, min(limit, 201)), before)

    def history(
        self, where: VisitFilter, limit: int = 50, offset: int = 0
    ) -> tuple[list[VisitView], int]:
        visits = self._visits.visits(where)
        page = visits[offset : offset + max(1, min(limit, 200))]
        return self._views(page), len(visits)

    def detail(self, session_id: str) -> VisitDetail | None:
        visit = self._visits.visit(session_id)
        if visit is None:
            return None
        (view,) = self._views([visit])
        return VisitDetail(view=view, timeline=tuple(self._repository.for_session(session_id)))

    def statistics(self, where: VisitFilter) -> Statistics:
        visits = self._visits.visits(where)
        links = self._links.facts([v.id for v in visits])
        states = Counter(v.state for v in visits)
        # How long a guest takes from Start to their finished photos.
        durations = [
            (v.photos_made_at - v.started_at).total_seconds() / 60
            for v in visits
            if v.photos_made_at is not None
        ]
        return Statistics(
            since=where.since,
            until=where.until,
            visits=len(visits),
            finished=sum(1 for v in visits if v.state in FINISHED and v.outputs),
            cancelled=states["cancelled"],
            abandoned=states["abandoned"],
            errors=states["error"],
            in_progress=sum(1 for v in visits if v.state not in FINISHED | ENDED_EARLY),
            photos=sum(v.photos for v in visits),
            retakes=sum(v.retakes for v in visits),
            failed_attempts=sum(v.failed_attempts for v in visits),
            outputs=sum(v.outputs for v in visits),
            decorated=sum(1 for v in visits if v.outputs and (v.filter or v.stickers)),
            links_opened=sum(1 for v in visits if links.get(v.id, _NO_LINK).opened),
            downloads=sum(links.get(v.id, _NO_LINK).downloads for v in visits),
            average_minutes=round(sum(durations) / len(durations), 1) if durations else None,
            by_layout=dict(Counter(v.layout for v in visits if v.layout).most_common()),
            # The booth's own clock: an event at 19:00 local time counts at 19, not at 12 UTC.
            by_hour=dict(sorted(Counter(v.started_at.astimezone().hour for v in visits).items())),
            by_filter=dict(Counter(v.filter or "none" for v in visits if v.outputs).most_common()),
        )

    def _views(self, visits: Sequence[Visit]) -> list[VisitView]:
        links = self._links.facts([v.id for v in visits])
        names = self._profiles.names()
        return [
            VisitView(visit=v, link=links.get(v.id, _NO_LINK), profile_name=names.get(v.profile_id))
            for v in visits
        ]


_NO_LINK = LinkFacts(issued=False, opened=False, downloads=0)
