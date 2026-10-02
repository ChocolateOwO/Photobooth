"""Activity routes for organizers (paired device + admin session), and the admin audit.

- GET /api/admin/activity                   the activity log, newest first, filtered, paged
- GET /api/admin/history                    guests' visits, newest first, filtered, paged
- GET /api/admin/history/{session_id}       one visit with its timeline
- GET /api/admin/statistics                 counts for a period and event

`AdminAudit` is an ASGI middleware on the kiosk app: after an organizer's change succeeds (or a
sign-in fails) it records which change it was, by whom and on what id. It never reads a request
body, so no password, name or setting value can reach the log.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import AwareDatetime
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import REGISTRY_STATE_KEY, ServiceRegistry, provide, require_device
from photobooth.modules.activity.domain import ActivityFilter, ActivityType, Actor
from photobooth.modules.activity.schemas import (
    ActivityPage,
    ActivityRecordResponse,
    HistoryPage,
    StatisticsResponse,
    VisitDetailResponse,
    VisitResponse,
)
from photobooth.modules.activity.service import ActivityService, VisitFilter

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-activity"],
    dependencies=[Depends(require_device), Depends(require_admin)],
)

Service = Annotated[ActivityService, Depends(provide(ActivityService))]
SessionId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
ProfileFilter = Annotated[
    str | None,
    Query(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
VisitState = Literal[
    "eligibility_ok",
    "capturing",
    "reviewing",
    "delivered",
    "completed",
    "cancelled",
    "abandoned",
    "error",
]


def _period(since: datetime | None, until: datetime | None) -> None:
    if since and until and until <= since:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="until must be after since"
        )


@router.get("/activity", response_model=ActivityPage)
def activity(
    service: Service,
    types: Annotated[list[ActivityType] | None, Query(alias="type")] = None,
    actors: Annotated[list[Actor] | None, Query(alias="actor")] = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
    before_at: AwareDatetime | None = None,
    before_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ActivityPage:
    _period(since, until)
    before = (before_at, before_id) if before_at and before_id else None
    records = service.search(
        ActivityFilter(types=types or (), actors=actors or (), since=since, until=until),
        limit + 1,
        before,
    )
    return ActivityPage(
        records=[ActivityRecordResponse.of(r) for r in records[:limit]],
        more=len(records) > limit,
    )


@router.get("/history", response_model=HistoryPage)
def history(
    service: Service,
    profile_id: ProfileFilter = None,
    state: Annotated[list[VisitState] | None, Query()] = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HistoryPage:
    _period(since, until)
    views, total = service.history(
        VisitFilter(since=since, until=until, profile_id=profile_id, states=state or ()),
        limit,
        offset,
    )
    return HistoryPage(visits=[VisitResponse.of(v) for v in views], total=total, offset=offset)


@router.get("/history/{session_id}", response_model=VisitDetailResponse)
def visit_detail(session_id: SessionId, service: Service) -> VisitDetailResponse:
    detail = service.detail(session_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such visit")
    return VisitDetailResponse.of(detail)


@router.get("/statistics", response_model=StatisticsResponse)
def statistics(
    service: Service,
    profile_id: ProfileFilter = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
) -> StatisticsResponse:
    _period(since, until)
    return StatisticsResponse.of(
        service.statistics(VisitFilter(since=since, until=until, profile_id=profile_id))
    )


# ---- the admin audit ------------------------------------------------------------------------

_MODULES = "photobooth.modules."
# Which organizer change each admin route is (by its module and function name), and where the id
# it acted on comes from: a path parameter, or the "id" of the answer for something new.
AUDITED: Mapping[str, tuple[ActivityType, str | None]] = {
    "auth.api.logout": (ActivityType.ADMIN_LOGOUT, None),
    "event_profiles.api.create_profile": (ActivityType.ADMIN_PROFILE_CREATED, "answer"),
    "event_profiles.api.update_profile": (ActivityType.ADMIN_PROFILE_UPDATED, "profile_id"),
    "event_profiles.api.duplicate_profile": (ActivityType.ADMIN_PROFILE_DUPLICATED, "answer"),
    "event_profiles.api.activate_profile": (ActivityType.ADMIN_PROFILE_ACTIVATED, "profile_id"),
    "event_profiles.api.delete_profile": (ActivityType.ADMIN_PROFILE_DELETED, "profile_id"),
    "event_profiles.api.restore_profile": (ActivityType.ADMIN_PROFILE_RESTORED, "profile_id"),
    "frames.api.upload_frame": (ActivityType.ADMIN_FRAME_UPLOADED, "answer"),
    "frames.api.replace_frame": (ActivityType.ADMIN_FRAME_REPLACED, "frame_id"),
    "frames.api.rename_frame": (ActivityType.ADMIN_FRAME_RENAMED, "frame_id"),
    "frames.api.delete_frame": (ActivityType.ADMIN_FRAME_DELETED, "frame_id"),
    "assets.api.upload_asset": (ActivityType.ADMIN_ASSET_UPLOADED, "answer"),
    "sessions.admin_api.start_test": (ActivityType.ADMIN_TEST_STARTED, None),
    "sessions.admin_api.clear_tests": (ActivityType.ADMIN_TESTS_CLEARED, None),
}
LOGIN = "auth.api.login"
PROFILE_EVENTS = frozenset(t for t, _ in AUDITED.values() if t.value.startswith("admin_profile"))
_MAX_ANSWER = 64 * 1024  # only small JSON answers are read for their "id"


def _route_of(scope: Scope) -> str | None:
    endpoint = scope.get("endpoint")
    if endpoint is None:
        return None
    module = getattr(endpoint, "__module__", "")
    if not module.startswith(_MODULES):
        return None
    return f"{module.removeprefix(_MODULES)}.{getattr(endpoint, '__name__', '')}"


def _answer_id(body: bytes) -> str | None:
    try:
        value = json.loads(body).get("id") if body else None
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and len(value) <= 64 else None


class AdminAudit:
    """Records organizers' changes after they succeed. Pure ASGI: it watches the answer go out
    and never changes it; a record that can not be kept never fails the request."""

    def __init__(self, app: ASGIApp, service: Callable[[Scope], ActivityService | None]) -> None:
        self._app = app
        self._service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") in {"GET", "HEAD", "OPTIONS"}
            or not str(scope.get("path", "")).startswith("/api/admin/")
        ):
            await self._app(scope, receive, send)
            return
        status_code = 0
        answer = bytearray()

        async def watch(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body" and len(answer) < _MAX_ANSWER:
                answer.extend(message.get("body", b"")[: _MAX_ANSWER - len(answer)])
            await send(message)

        await self._app(scope, receive, watch)
        self._audit(scope, status_code, bytes(answer))

    def _audit(self, scope: Scope, status_code: int, answer: bytes) -> None:
        route = _route_of(scope)
        service = self._service(scope)
        if route is None or service is None:
            return
        principal = (scope.get("state") or {}).get("admin_principal")
        username = getattr(principal, "username", None)
        if route == LOGIN:
            if 200 <= status_code < 300:
                service.record(ActivityType.ADMIN_LOGIN, admin_username=username)
            elif status_code in {401, 429}:
                service.record(
                    ActivityType.ADMIN_LOGIN_FAILED,
                    payload={"reason": "throttled" if status_code == 429 else "refused"},
                )
            return
        audited = AUDITED.get(route)
        if audited is None or not 200 <= status_code < 300:
            return
        kind, source = audited
        params: dict[str, Any] = scope.get("path_params") or {}
        target = _answer_id(answer) if source == "answer" else params.get(source or "")
        service.record(
            kind,
            admin_username=username,
            profile_id=target if kind in PROFILE_EVENTS else None,
            payload={"target": target} if isinstance(target, str) else None,
        )


def registry_service(scope: Scope) -> ActivityService | None:
    """The activity service of the app this request reached (None before startup)."""
    app = scope.get("app")
    registry = getattr(getattr(app, "state", None), REGISTRY_STATE_KEY, None)
    if not isinstance(registry, ServiceRegistry):
        return None
    try:
        return registry.get(ActivityService)
    except KeyError:
        return None
