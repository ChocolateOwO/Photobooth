"""Retention routes for organizers (paired device + admin session).

- GET  /api/admin/retention/policy                  the booth's policy
- PUT  /api/admin/retention/policy                  change it (revision-checked)
- POST /api/admin/retention/run                     dry run, or delete now (confirm "DELETE")
- GET  /api/admin/retention/runs                    recent cleanups
- POST /api/admin/retention/events/{id}/remove      delete a deleted event for good (dry run first)

Deleting can not be undone: a real run, and the permanent deletion of an event, are refused
unless the request carries the word DELETE.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from starlette.concurrency import run_in_threadpool

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import provide, require_device
from photobooth.modules.retention.domain import (
    EventNotFoundError,
    PolicyChangedError,
    RetentionError,
    Trigger,
)
from photobooth.modules.retention.schemas import (
    EventRemovalResponse,
    RetentionPolicyBody,
    RetentionPolicyResponse,
    RetentionReportResponse,
    RetentionRunResponse,
    RunBody,
)
from photobooth.modules.retention.service import RetentionService

router = APIRouter(
    prefix="/api/admin/retention",
    tags=["admin-retention"],
    dependencies=[Depends(require_device), Depends(require_admin)],
)

Service = Annotated[RetentionService, Depends(provide(RetentionService))]
ProfileId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
CONFIRMATION = "DELETE"


def _confirmed(dry_run: bool, confirm: str | None) -> None:
    if not dry_run and confirm != CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"deleting can not be undone: confirm with the word {CONFIRMATION}",
        )


@router.get("/policy", response_model=RetentionPolicyResponse)
def policy(service: Service) -> RetentionPolicyResponse:
    return RetentionPolicyResponse.of(service.policy())


@router.put("/policy", response_model=RetentionPolicyResponse)
def save_policy(body: RetentionPolicyBody, service: Service) -> RetentionPolicyResponse:
    try:
        saved = service.update_policy(body.to_domain(), body.revision)
    except RetentionError as exc:
        stale = "changed meanwhile" in str(exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT
            if stale
            else status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return RetentionPolicyResponse.of(saved)


@router.post("/run", response_model=RetentionReportResponse)
async def run(body: RunBody, service: Service) -> RetentionReportResponse:
    _confirmed(body.dry_run, body.confirm)
    if not body.dry_run and body.policy_revision is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="say which policy the check was made under (policy_revision)",
        )
    try:
        report = await run_in_threadpool(
            service.run, Trigger.MANUAL, body.dry_run, body.policy_revision
        )
    except PolicyChangedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RetentionReportResponse.of(report)


@router.get("/runs", response_model=list[RetentionRunResponse])
def runs(
    service: Service, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[RetentionRunResponse]:
    return [RetentionRunResponse.of(r) for r in service.runs(limit)]


@router.post("/events/{profile_id}/remove", response_model=EventRemovalResponse)
async def remove_event(
    profile_id: ProfileId, body: RunBody, service: Service
) -> EventRemovalResponse:
    _confirmed(body.dry_run, body.confirm)
    try:
        visits, size, _failed = await run_in_threadpool(
            service.remove_event, profile_id, body.dry_run
        )
    except EventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RetentionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return EventRemovalResponse(dry_run=body.dry_run, visits=visits, bytes=size)
