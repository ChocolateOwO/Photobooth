"""Read-only template routes (kiosk listener; no device cookie needed, no mutation)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from photobooth.core.web import provide
from photobooth.modules.templates.domain import TemplateNotFoundError
from photobooth.modules.templates.schemas import TemplateSpec, TemplateSummary
from photobooth.modules.templates.service import TemplateSpecService

router = APIRouter(prefix="/api/templates", tags=["templates"])

Service = Annotated[TemplateSpecService, Depends(provide(TemplateSpecService))]
Key = Annotated[str, Path(pattern=r"^[a-z0-9_]{1,64}$")]
Version = Annotated[int | None, Query(ge=1, le=9999)]


def _not_found(exc: TemplateNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _png(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@router.get("", response_model=list[TemplateSummary])
def list_templates(service: Service) -> list[TemplateSummary]:
    return [TemplateSummary.of(t) for t in service.list_latest()]


@router.get("/{key}", response_model=TemplateSpec)
def template_spec(service: Service, key: Key, version: Version = None) -> TemplateSpec:
    try:
        return TemplateSpec.of(service.get(key, version))
    except TemplateNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/{key}/blank.png", response_class=Response, responses={200: {"content": {"image/png": {}}}}
)
def blank_png(service: Service, key: Key, version: Version = None) -> Response:
    try:
        template = service.get(key, version)
        return _png(service.blank_png(key, version), f"{key}.v{template.version}.blank.png")
    except TemplateNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/{key}/guide.png", response_class=Response, responses={200: {"content": {"image/png": {}}}}
)
def guide_png(service: Service, key: Key, version: Version = None) -> Response:
    try:
        template = service.get(key, version)
        return _png(service.guide_png(key, version), f"{key}.v{template.version}.guide.png")
    except TemplateNotFoundError as exc:
        raise _not_found(exc) from exc
