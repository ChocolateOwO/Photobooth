"""Frame routes under /api/admin/frames (paired device + admin session).

Frames are finished transparent PNGs made outside this app. Here they are only validated against a
template, stored unchanged, listed, previewed, replaced, renamed and deleted.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from starlette.concurrency import run_in_threadpool

from photobooth.core.admin_gate import require_admin
from photobooth.core.uploads import UploadAdmission, multipart_openapi, read_upload
from photobooth.core.web import provide, require_device
from photobooth.modules.frames.domain import (
    FrameInUseError,
    FrameNotFoundError,
    FrameReadOnlyError,
    FrameValidationError,
)
from photobooth.modules.frames.schemas import FrameResponse, RenameFrameBody
from photobooth.modules.frames.service import FrameService
from photobooth.modules.rendering.domain import RenderBusyError, RenderError
from photobooth.modules.rendering.service import RenderService
from photobooth.modules.templates.domain import TemplateNotFoundError

router = APIRouter(
    prefix="/api/admin/frames",
    tags=["admin-frames"],
    dependencies=[Depends(require_device), Depends(require_admin)],
)

Service = Annotated[FrameService, Depends(provide(FrameService))]
Renderer = Annotated[RenderService, Depends(provide(RenderService))]
Admission = Annotated[UploadAdmission, Depends(provide(UploadAdmission))]
FrameId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
TemplateKey = Annotated[str, Query(pattern=r"^[a-z0-9_]{1,64}$")]
# Frame rule: at most 10 MB, plus room for multipart framing and the two text fields.
MAX_UPLOAD_BODY = 10 * 1024 * 1024 + 64 * 1024
UPLOAD_OPENAPI = multipart_openapi(
    {
        "template_key": {"type": "string", "examples": ["strip_2x6"]},
        "name": {"type": "string", "examples": ["Expo blue border"]},
    }
)
REPLACE_OPENAPI = multipart_openapi({})


def _read_only(exc: FrameReadOnlyError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _invalid(exc: FrameValidationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="; ".join(exc.problems)
    )


@router.get("", response_model=list[FrameResponse])
def list_frames(service: Service, template_key: TemplateKey | None = None) -> list[FrameResponse]:
    try:
        frames = service.list_frames(template_key)
    except FrameValidationError as exc:
        raise _invalid(exc) from exc
    return [FrameResponse.of(frame) for frame in frames]


@router.post(
    "",
    response_model=FrameResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=UPLOAD_OPENAPI,
)
async def upload_frame(request: Request, service: Service, admission: Admission) -> FrameResponse:
    if not admission.try_acquire():
        raise admission.busy()
    try:
        values, data = await read_upload(request, MAX_UPLOAD_BODY, ("template_key", "name"))
        frame = await run_in_threadpool(
            service.upload, values["template_key"], values["name"], data
        )
        return FrameResponse.of(frame)
    except FrameValidationError as exc:
        raise _invalid(exc) from exc
    finally:
        admission.release()


@router.get("/{frame_id}", response_model=FrameResponse)
def frame_metadata(frame_id: FrameId, service: Service) -> FrameResponse:
    try:
        return FrameResponse.of(service.get(frame_id))
    except FrameNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{frame_id}/content",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def frame_content(frame_id: FrameId, service: Service) -> Response:
    """The original uploaded PNG, byte for byte."""
    try:
        frame, data = await run_in_threadpool(service.content, frame_id)
    except FrameNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{frame.template_key}.frame.png"',
            "Cache-Control": "private, no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "ETag": f'"{frame.sha256}"',
        },
    )


@router.get(
    "/{frame_id}/preview/{output_index}.jpg",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
async def frame_preview(
    frame_id: FrameId,
    output_index: Annotated[int, Path(ge=1, le=16)],
    service: Service,
    renderer: Renderer,
) -> Response:
    """Sample output: numbered placeholder photos with this frame composited on top."""
    try:
        frame, data = await run_in_threadpool(service.content, frame_id)
        future = renderer.render_frame_preview(frame.template_key, output_index, data)
        rendered = await run_in_threadpool(future.result)
    except FrameNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RenderBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the renderer is busy; try again",
            headers={"Retry-After": "2"},
        ) from exc
    except RenderError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return Response(
        content=rendered.data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{frame_id}/replace", response_model=FrameResponse, openapi_extra=REPLACE_OPENAPI)
async def replace_frame(
    frame_id: FrameId, request: Request, service: Service, admission: Admission
) -> FrameResponse:
    """Swap in a corrected PNG. Profiles keep their selection; the old file is kept unchanged."""
    if not admission.try_acquire():
        raise admission.busy()
    try:
        _values, data = await read_upload(request, MAX_UPLOAD_BODY, ())
        frame = await run_in_threadpool(service.replace_file, frame_id, data)
        return FrameResponse.of(frame)
    except FrameNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FrameReadOnlyError as exc:
        raise _read_only(exc) from exc
    except FrameValidationError as exc:
        raise _invalid(exc) from exc
    finally:
        admission.release()


@router.put("/{frame_id}/name", response_model=FrameResponse)
def rename_frame(frame_id: FrameId, body: RenameFrameBody, service: Service) -> FrameResponse:
    try:
        return FrameResponse.of(service.rename(frame_id, body.name))
    except FrameNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FrameReadOnlyError as exc:
        raise _read_only(exc) from exc
    except FrameValidationError as exc:
        raise _invalid(exc) from exc


@router.delete("/{frame_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_frame(frame_id: FrameId, service: Service) -> None:
    try:
        service.delete(frame_id)
    except FrameNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FrameReadOnlyError as exc:
        raise _read_only(exc) from exc
    except FrameInUseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
