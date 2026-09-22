"""Participant booth routes under /api/booth (paired kiosk device; no admin session).

- GET  /api/booth/frames                      frames offered by the active event, in order
- GET  /api/booth/frames/{id}/preview.jpg     rendered sample of an offered frame
- POST /api/booth/frame-choice                confirm a frame; returns its capture/output plan

Only what participants need is returned: no file, storage or built-in/uploaded information.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from starlette.concurrency import run_in_threadpool

from photobooth.core.web import provide, require_device
from photobooth.modules.booth.domain import (
    FrameNotOfferedError,
    NoActiveEventError,
    PreviewBusyError,
    PreviewFailedError,
)
from photobooth.modules.booth.schemas import (
    FrameChoiceBody,
    FrameMenuResponse,
    FramePlanResponse,
)
from photobooth.modules.booth.service import BoothService

router = APIRouter(prefix="/api/booth", tags=["booth"], dependencies=[Depends(require_device)])

Service = Annotated[BoothService, Depends(provide(BoothService))]
FrameId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/frames", response_model=FrameMenuResponse)
def frame_menu(service: Service, response: Response) -> FrameMenuResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return FrameMenuResponse.of(service.menu())
    except NoActiveEventError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/frames/{frame_id}/preview.jpg",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
async def frame_preview(frame_id: FrameId, service: Service) -> Response:
    try:
        data = await run_in_threadpool(service.preview, frame_id)
    except (NoActiveEventError, FrameNotOfferedError) as exc:
        raise _not_found(exc) from exc
    except PreviewBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the renderer is busy; try again",
            headers={"Retry-After": "2"},
        ) from exc
    except PreviewFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/frame-choice", response_model=FramePlanResponse)
def choose_frame(body: FrameChoiceBody, service: Service) -> FramePlanResponse:
    """Confirm the participant's frame for the next session (capture starts in a later phase)."""
    try:
        return FramePlanResponse.of(service.choose(body.frame_id))
    except (NoActiveEventError, FrameNotOfferedError) as exc:
        raise _not_found(exc) from exc
