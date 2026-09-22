"""Event Profile admin routes under /api/admin/profiles (paired device + admin session)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import provide, require_device
from photobooth.modules.event_profiles.domain import (
    EventProfile,
    ProfileConflictError,
    ProfileError,
    ProfileNotFoundError,
    ProfileValidationError,
)
from photobooth.modules.event_profiles.schemas import (
    DuplicateBody,
    EventProfileResponse,
    ProblemResponse,
    ProfileSettingsBody,
    ProfileUpdateBody,
)
from photobooth.modules.event_profiles.service import EventProfileService

router = APIRouter(
    prefix="/api/admin/profiles",
    tags=["admin-profiles"],
    dependencies=[Depends(require_device), Depends(require_admin)],
    responses={404: {"model": ProblemResponse}, 409: {"model": ProblemResponse}},
)

Service = Annotated[EventProfileService, Depends(provide(EventProfileService))]
ProfileId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


def _run(service: EventProfileService, action: Callable[[], EventProfile]) -> EventProfileResponse:
    try:
        profile = action()
        return EventProfileResponse.of(profile, service.available_layouts(profile.settings))
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(exc.problems),
        ) from exc
    except ProfileConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProfileError as exc:  # pragma: no cover - every subclass is mapped above
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[EventProfileResponse])
def list_profiles(
    service: Service, include_deleted: Annotated[bool, Query()] = False
) -> list[EventProfileResponse]:
    return [
        EventProfileResponse.of(p, service.available_layouts(p.settings))
        for p in service.list_profiles(include_deleted)
    ]


@router.post("", response_model=EventProfileResponse, status_code=status.HTTP_201_CREATED)
def create_profile(body: ProfileSettingsBody, service: Service) -> EventProfileResponse:
    return _run(service, lambda: service.create(body.to_domain(service.default_available_frames())))


@router.get("/{profile_id}", response_model=EventProfileResponse)
def get_profile(profile_id: ProfileId, service: Service) -> EventProfileResponse:
    return _run(service, lambda: service.get(profile_id))


@router.put("/{profile_id}", response_model=EventProfileResponse)
def update_profile(
    profile_id: ProfileId, body: ProfileUpdateBody, service: Service
) -> EventProfileResponse:
    return _run(service, lambda: service.update(profile_id, body.to_domain(), body.revision))


@router.post(
    "/{profile_id}/duplicate",
    response_model=EventProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_profile(
    profile_id: ProfileId, service: Service, body: DuplicateBody | None = None
) -> EventProfileResponse:
    name = None if body is None else body.name
    return _run(service, lambda: service.duplicate(profile_id, name))


@router.post("/{profile_id}/activate", response_model=EventProfileResponse)
def activate_profile(profile_id: ProfileId, service: Service) -> EventProfileResponse:
    return _run(service, lambda: service.activate(profile_id))


@router.delete("/{profile_id}", response_model=EventProfileResponse)
def delete_profile(
    profile_id: ProfileId, service: Service, revision: Annotated[int, Query(ge=1)]
) -> EventProfileResponse:
    """Soft delete: the row and its assets stay; it can be restored."""
    return _run(service, lambda: service.soft_delete(profile_id, revision))


@router.post("/{profile_id}/restore", response_model=EventProfileResponse)
def restore_profile(profile_id: ProfileId, service: Service) -> EventProfileResponse:
    return _run(service, lambda: service.restore(profile_id))
