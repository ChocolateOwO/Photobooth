"""Retention routes for organizers (paired device + admin session).

- GET    /api/admin/retention/policies                 the named policies (with their use)
- POST   /api/admin/retention/policies                 add one
- PUT    /api/admin/retention/policies/{id}            change one (checked; new visits only)
- DELETE /api/admin/retention/policies/{id}            delete one no Event Profile uses
- POST   /api/admin/retention/policies/{id}/default    new Event Profiles start with this one
- GET    /api/admin/retention/housekeeping             the booth-wide settings
- PUT    /api/admin/retention/housekeeping             change them (revision-checked)
- POST   /api/admin/retention/run                      dry run, or delete now (confirm "DELETE")
- GET    /api/admin/retention/runs                     recent cleanups
- POST   /api/admin/retention/events/{id}/remove       delete a deleted event for good

Deleting can not be undone: a real run, and the permanent deletion of an event, are refused
unless the request carries the word DELETE.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from starlette.concurrency import run_in_threadpool

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import provide, require_device
from photobooth.modules.retention.domain import (
    EventNotFoundError,
    PolicyChangedError,
    PolicyInUseError,
    PolicyNameTakenError,
    PolicyNotFoundError,
    RetentionError,
    StaleEditError,
    Trigger,
)
from photobooth.modules.retention.schemas import (
    EventRemovalResponse,
    HousekeepingBody,
    HousekeepingResponse,
    RemoveBody,
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
Uuid = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
CONFIRMATION = "DELETE"


def _confirmed(dry_run: bool, confirm: str | None) -> None:
    if not dry_run and confirm != CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"deleting can not be undone: confirm with the word {CONFIRMATION}",
        )


def _refused(exc: RetentionError) -> HTTPException:
    if isinstance(exc, PolicyNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, StaleEditError | PolicyInUseError | PolicyNameTakenError):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=str(exc))


def _shown(service: RetentionService, policy_id: str) -> RetentionPolicyResponse:
    return RetentionPolicyResponse.of(service.policy(policy_id), service.usage(policy_id))


@router.get("/policies", response_model=list[RetentionPolicyResponse])
def policies(service: Service) -> list[RetentionPolicyResponse]:
    return [RetentionPolicyResponse.of(p, service.usage(p.id)) for p in service.policies()]


@router.post(
    "/policies", response_model=RetentionPolicyResponse, status_code=status.HTTP_201_CREATED
)
def create_policy(body: RetentionPolicyBody, service: Service) -> RetentionPolicyResponse:
    try:
        made = service.create_policy(body.to_domain())
    except RetentionError as exc:
        raise _refused(exc) from exc
    return _shown(service, made.id)


@router.put("/policies/{policy_id}", response_model=RetentionPolicyResponse)
def update_policy(
    policy_id: Uuid, body: RetentionPolicyBody, service: Service
) -> RetentionPolicyResponse:
    try:
        saved = service.update_policy(policy_id, body.to_domain(), body.revision)
    except RetentionError as exc:
        raise _refused(exc) from exc
    return _shown(service, saved.id)


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(policy_id: Uuid, service: Service) -> Response:
    try:
        service.delete_policy(policy_id)
    except RetentionError as exc:
        raise _refused(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/policies/{policy_id}/default", response_model=RetentionPolicyResponse)
def make_default(policy_id: Uuid, service: Service) -> RetentionPolicyResponse:
    try:
        made = service.make_default(policy_id)
    except RetentionError as exc:
        raise _refused(exc) from exc
    return _shown(service, made.id)


@router.get("/housekeeping", response_model=HousekeepingResponse)
def housekeeping(service: Service) -> HousekeepingResponse:
    return HousekeepingResponse.of(service.housekeeping())


@router.put("/housekeeping", response_model=HousekeepingResponse)
def save_housekeeping(body: HousekeepingBody, service: Service) -> HousekeepingResponse:
    try:
        saved = service.update_housekeeping(body.to_domain(), body.revision)
    except RetentionError as exc:
        raise _refused(exc) from exc
    return HousekeepingResponse.of(saved)


@router.post("/run", response_model=RetentionReportResponse)
async def run(body: RunBody, service: Service) -> RetentionReportResponse:
    _confirmed(body.dry_run, body.confirm)
    if not body.dry_run and body.housekeeping_revision is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="say which settings the check was made under (housekeeping_revision)",
        )
    try:
        report = await run_in_threadpool(
            service.run, Trigger.MANUAL, body.dry_run, body.housekeeping_revision
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
    profile_id: Uuid, body: RemoveBody, service: Service
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
