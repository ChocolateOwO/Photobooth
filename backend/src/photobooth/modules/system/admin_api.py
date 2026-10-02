"""System details for organizers (paired device + admin session).

- GET /api/admin/system   versions, health, disk, addresses and the last cleanup of this booth

Nothing secret is shown: no token, password, pairing code or file path beyond the two addresses
the booth already shows (its own screen and the address guests' phones use).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import provide, require_device
from photobooth.modules.system.service import SystemDetailsService

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-system"],
    dependencies=[Depends(require_device), Depends(require_admin)],
)

Service = Annotated[SystemDetailsService, Depends(provide(SystemDetailsService))]


class SystemDetailsResponse(BaseModel):
    instance: str
    profile: str
    app_version: str
    api_version: int
    schema_revision: str | None
    git_commit: str | None
    started_at: datetime
    database: str
    storage_bytes: int
    disk_free_bytes: int
    disk_total_bytes: int
    kiosk_url: str
    delivery_url: str
    active_event: str | None
    visits_in_progress: int
    last_cleanup_at: datetime | None
    last_cleanup_errors: list[str]


@router.get("/system", response_model=SystemDetailsResponse)
def system(service: Service, response: Response) -> SystemDetailsResponse:
    response.headers["Cache-Control"] = "no-store"
    details = service.details()
    return SystemDetailsResponse(
        instance=details.version.instance,
        profile=details.facts.profile,
        app_version=details.version.app_version,
        api_version=details.version.api_version,
        schema_revision=details.version.schema_revision,
        git_commit=details.version.git_commit,
        started_at=details.facts.started_at,
        database=details.health.database.value,
        storage_bytes=details.facts.storage_bytes,
        disk_free_bytes=details.facts.disk_free_bytes,
        disk_total_bytes=details.facts.disk_total_bytes,
        kiosk_url=details.facts.kiosk_url,
        delivery_url=details.facts.delivery_url,
        active_event=details.facts.active_event,
        visits_in_progress=details.facts.visits_in_progress,
        last_cleanup_at=details.facts.last_cleanup_at,
        last_cleanup_errors=list(details.facts.last_cleanup_errors),
    )
