"""Read-only render preview: a template rendered with numbered placeholder photos."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from photobooth.core.web import provide
from photobooth.modules.rendering.domain import RenderError
from photobooth.modules.rendering.service import RenderService
from photobooth.modules.templates.domain import TemplateNotFoundError

router = APIRouter(prefix="/api/render", tags=["rendering"])

Service = Annotated[RenderService, Depends(provide(RenderService))]


@router.get(
    "/samples/{key}/{output_index}.jpg",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def sample_output(
    service: Service,
    key: Annotated[str, Path(pattern=r"^[a-z0-9_]{1,64}$")],
    output_index: Annotated[int, Path(ge=1, le=16)],
    version: Annotated[int | None, Query(ge=1, le=9999)] = None,
) -> Response:
    try:
        rendered = service.render_sample(key, output_index, version)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=rendered.data,
        media_type=rendered.media_type,
        headers={
            "Content-Disposition": f'inline; filename="{key}.sample.{output_index}.jpg"',
            "Cache-Control": "no-cache",
            "X-Photobooth-Capture-Ids": ",".join(rendered.capture_ids),
        },
    )
