"""Thin routes: /api/health and /api/version (read-only, no device cookie required)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from photobooth.core.web import provide
from photobooth.modules.system.schemas import HealthResponse, VersionResponse
from photobooth.modules.system.service import SystemService

router = APIRouter(prefix="/api", tags=["system"])

Service = Annotated[SystemService, Depends(provide(SystemService))]


@router.get("/health", response_model=HealthResponse)
def health(service: Service, response: Response) -> HealthResponse:
    report = service.health()
    if report.status.value != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status=report.status.value,
        instance=report.instance,
        database=report.database.value,
    )


@router.get("/version", response_model=VersionResponse)
def version(service: Service) -> VersionResponse:
    info = service.version()
    return VersionResponse(
        app_version=info.app_version,
        api_version=info.api_version,
        instance=info.instance,
        schema_revision=info.schema_revision,
        git_commit=info.git_commit,
    )
