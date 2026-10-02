"""Participant session routes under /api/booth/sessions (paired kiosk device; no admin session).

- POST /api/booth/sessions                       start the visit (idempotent per device key)
- GET  /api/booth/sessions/current               the visit this device is in the middle of
- GET  /api/booth/sessions/{id}                  read one visit
- POST /api/booth/sessions/{id}/frame            confirm the frame; the photo count follows it
- POST /api/booth/sessions/{id}/captures         send one photo (idempotent per key)
- POST /api/booth/sessions/{id}/retake           take a photo (or the set) again
- POST /api/booth/sessions/{id}/finish           every photo is in; the guest reviews them
- GET  /api/booth/sessions/{id}/decorate         the finished photos' layout, for decorating
- GET  /api/booth/sessions/{id}/frame.png        the visit's own frame (unchanged)
- POST /api/booth/sessions/{id}/render           make the finished photos, decorated as the guest
                                                 chose (idempotent per key)
- GET  /api/booth/sessions/{id}/outputs/{o}.jpg  one finished photo, for this booth screen
- POST /api/booth/sessions/{id}/delivery         the take-home link and its QR code
- POST /api/booth/sessions/{id}/give-up          the participant leaves (or is done)

Every answer describes only the visit: no profile name, asset id, storage key or file path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from starlette.concurrency import run_in_threadpool

from photobooth.core.uploads import UploadAdmission, multipart_openapi, read_upload
from photobooth.core.web import device_identity, provide, require_device
from photobooth.modules.sessions.domain import (
    MAX_CAPTURE_BYTES,
    BoothSession,
    CaptureNotFoundError,
    CaptureRefusedError,
    DecorationRefusedError,
    EligibilityRefusedError,
    FrameFileNotFoundError,
    FrameNotOfferedError,
    IdempotencyReuseError,
    NoActiveEventError,
    OperationFailedError,
    OutputNotFoundError,
    RenderBusyError,
    RenderFailedError,
    SessionClosedError,
    SessionNotFoundError,
    StaleAttemptError,
    StaleSessionError,
    TooManyCapturesError,
    TransitionRefusedError,
)
from photobooth.modules.sessions.schemas import (
    BoothSessionResponse,
    CaptureResponse,
    ChooseFrameBody,
    DecorateLayoutResponse,
    DecorateOutputResponse,
    DeliveryLinkResponse,
    RenderBody,
    RetakeBody,
    StartSessionBody,
)
from photobooth.modules.sessions.service import BoothSessionService

router = APIRouter(
    prefix="/api/booth/sessions", tags=["booth"], dependencies=[Depends(require_device)]
)

Service = Annotated[BoothSessionService, Depends(provide(BoothSessionService))]
Device = Annotated[str, Depends(device_identity)]
Admission = Annotated[UploadAdmission, Depends(provide(UploadAdmission))]
SessionId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
# One JPEG frame from the booth camera, plus room for the multipart framing and text fields.
MAX_CAPTURE_BODY = MAX_CAPTURE_BYTES + 64 * 1024
CAPTURE_OPENAPI = multipart_openapi(
    {
        "idempotency_key": {"type": "string", "examples": ["a1b2c3d4e5f6a7b8"]},
        "shot_index": {"type": "string", "examples": ["1"]},
        "attempt_no": {"type": "string", "examples": ["1"]},
    }
)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _view(service: BoothSessionService, session: BoothSession) -> BoothSessionResponse:
    shots = service.progress(session.id) if session.expected_capture_count else []
    return BoothSessionResponse.of(session, shots, service.finished_outputs(session.id))


_IMAGE_HEADERS = {
    "Content-Disposition": "inline",
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
}


@router.post("", response_model=BoothSessionResponse, status_code=status.HTTP_201_CREATED)
def start_session(body: StartSessionBody, service: Service, device: Device) -> BoothSessionResponse:
    """Begin a visit from the active event, with its settings frozen for the whole session."""
    try:
        session = service.start(device, body.idempotency_key)
    except NoActiveEventError as exc:
        raise _not_found(exc) from exc
    except EligibilityRefusedError as exc:
        raise _conflict(exc) from exc
    except IdempotencyReuseError as exc:
        raise _refused(exc) from exc
    return _view(service, session)


@router.get("/current", response_model=BoothSessionResponse | None)
def current_session(
    service: Service, device: Device, response: Response
) -> BoothSessionResponse | None:
    """What this device was doing (after a reload or a step back), or null."""
    response.headers["Cache-Control"] = "no-store"
    session = service.current(device)
    return _view(service, session) if session else None


@router.get("/{session_id}", response_model=BoothSessionResponse)
def read_session(session_id: SessionId, service: Service, device: Device) -> BoothSessionResponse:
    try:
        return _view(service, service.read(device, session_id))
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/{session_id}/frame", response_model=BoothSessionResponse)
def choose_frame(
    session_id: SessionId, body: ChooseFrameBody, service: Service, device: Device
) -> BoothSessionResponse:
    """Confirm the frame: it fixes the template, the photo count and the outputs."""
    try:
        return _view(service, service.choose_frame(device, session_id, body.frame_id))
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except FrameNotOfferedError as exc:
        raise _not_found(exc) from exc
    except (SessionClosedError, StaleSessionError, TransitionRefusedError) as exc:
        raise _conflict(exc) from exc


@router.post(
    "/{session_id}/captures",
    response_model=CaptureResponse,
    openapi_extra=CAPTURE_OPENAPI,
)
async def add_capture(
    session_id: SessionId,
    request: Request,
    service: Service,
    device: Device,
    admission: Admission,
) -> CaptureResponse:
    """One photo of this session. The same key twice returns the first answer, stores nothing."""
    if not admission.try_acquire():
        raise admission.busy()
    try:
        values, data = await read_upload(
            request, MAX_CAPTURE_BODY, ("idempotency_key", "shot_index", "attempt_no")
        )
        try:
            shot_index = int(values["shot_index"])
            attempt_no = int(values["attempt_no"])
        except ValueError as exc:
            raise _refused(ValueError("shot_index and attempt_no must be whole numbers")) from exc
        outcome = await run_in_threadpool(
            service.add_capture,
            device,
            session_id,
            idempotency_key=values["idempotency_key"],
            shot_index=shot_index,
            attempt_no=attempt_no,
            data=data,
        )
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except (SessionClosedError, StaleSessionError, TransitionRefusedError) as exc:
        raise _conflict(exc) from exc
    except StaleAttemptError as exc:
        raise _conflict(exc) from exc
    except TooManyCapturesError as exc:
        raise _conflict(exc) from exc
    except IdempotencyReuseError as exc:
        raise _refused(exc) from exc
    except OperationFailedError as exc:
        raise _conflict(exc) from exc
    except CaptureRefusedError as exc:
        raise _refused(exc) from exc
    finally:
        admission.release()
    return CaptureResponse.of(outcome, service.progress(session_id))


@router.post("/{session_id}/retake", response_model=BoothSessionResponse)
def retake(
    session_id: SessionId, body: RetakeBody, service: Service, device: Device
) -> BoothSessionResponse:
    """Take one photo again, or the whole set, as the event's retake setting allows."""
    shots = [body.shot_index] if body.shot_index is not None else None
    try:
        return _view(service, service.retake(device, session_id, shots, body.state_version))
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except (SessionClosedError, StaleSessionError, TransitionRefusedError) as exc:
        raise _conflict(exc) from exc
    except TooManyCapturesError as exc:
        raise _conflict(exc) from exc


@router.post("/{session_id}/finish", response_model=BoothSessionResponse)
def finish(session_id: SessionId, service: Service, device: Device) -> BoothSessionResponse:
    """Every photo is in; the camera step is over and the finished photos come next."""
    try:
        return _view(service, service.finish_capturing(device, session_id))
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except (SessionClosedError, StaleSessionError, TransitionRefusedError) as exc:
        raise _conflict(exc) from exc


@router.post(
    "/{session_id}/render",
    response_model=BoothSessionResponse,
    responses={503: {"description": "The render worker is busy; retry with the same key."}},
)
async def render(
    session_id: SessionId, body: RenderBody, service: Service, device: Device
) -> BoothSessionResponse:
    """Make the finished photos (300 DPI sRGB JPEG) from this visit's own photos and frame."""
    decoration = body.decoration.model_dump() if body.decoration is not None else None
    try:
        outcome = await run_in_threadpool(
            service.render, device, session_id, body.idempotency_key, decoration
        )
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except DecorationRefusedError as exc:
        raise _refused(exc) from exc
    except RenderBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "2"},
        ) from exc
    except (
        SessionClosedError,
        StaleSessionError,
        TransitionRefusedError,
        RenderFailedError,
        OperationFailedError,
    ) as exc:
        raise _conflict(exc) from exc
    except IdempotencyReuseError as exc:
        raise _refused(exc) from exc
    return _view(service, outcome.session)


@router.get(
    "/{session_id}/outputs/{output_id}.jpg",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def output_photo(
    session_id: SessionId, output_id: SessionId, service: Service, device: Device
) -> Response:
    """A finished photo of this visit, shown on the booth screen that made it."""
    try:
        data = service.output_photo(device, session_id, output_id)
    except (SessionNotFoundError, OutputNotFoundError) as exc:
        raise _not_found(exc) from exc
    return Response(content=data, media_type="image/jpeg", headers=_IMAGE_HEADERS)


@router.get("/{session_id}/decorate", response_model=DecorateLayoutResponse)
def decorate_layout(
    session_id: SessionId, service: Service, device: Device, response: Response
) -> DecorateLayoutResponse:
    """The finished photos as they will be composed, so the booth previews the decoration on
    the very slots, crops and frame the server uses."""
    response.headers["Cache-Control"] = "no-store"
    try:
        layouts = service.decorate_layout(device, session_id)
        session = service.read(device, session_id)
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except (SessionClosedError, TransitionRefusedError) as exc:
        raise _conflict(exc) from exc
    except RenderFailedError as exc:
        raise _conflict(exc) from exc
    versions = {
        shot.capture_id: shot.version for shot in service.progress(session_id) if shot.capture_id
    }
    selection = session.selection
    return DecorateLayoutResponse(
        mirror=session.mirror,
        frame_url=f"/api/booth/sessions/{session_id}/frame.png"
        + (f"?v={selection.frame_sha256[:16]}" if selection else ""),
        outputs=[DecorateOutputResponse.of(layout, versions) for layout in layouts],
    )


@router.get(
    "/{session_id}/frame.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def frame_file(session_id: SessionId, service: Service, device: Device) -> Response:
    """The frame this visit pinned, for its own booth screen. Never another frame."""
    try:
        data = service.frame_file(device, session_id)
    except (SessionNotFoundError, FrameFileNotFoundError) as exc:
        raise _not_found(exc) from exc
    return Response(content=data, media_type="image/png", headers=_IMAGE_HEADERS)


@router.post("/{session_id}/delivery", response_model=DeliveryLinkResponse)
def delivery_link(
    session_id: SessionId, service: Service, device: Device, response: Response
) -> DeliveryLinkResponse:
    """The guest's take-home link and QR code. A reload shows the same code while it is
    remembered; after a restart a new code replaces the old one."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return DeliveryLinkResponse.of(service.delivery_link(device, session_id))
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except (SessionClosedError, TransitionRefusedError) as exc:
        raise _conflict(exc) from exc


@router.get(
    "/{session_id}/captures/{capture_id}.jpg",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def capture_photo(
    session_id: SessionId, capture_id: SessionId, service: Service, device: Device
) -> Response:
    """A photo of this visit, shown back on the booth screen that took it."""
    try:
        data = service.photo(device, session_id, capture_id)
    except (SessionNotFoundError, CaptureNotFoundError) as exc:
        raise _not_found(exc) from exc
    return Response(content=data, media_type="image/jpeg", headers=_IMAGE_HEADERS)


@router.post("/{session_id}/give-up", response_model=BoothSessionResponse)
def give_up(session_id: SessionId, service: Service, device: Device) -> BoothSessionResponse:
    """The participant leaves the booth: the visit ends and takes no more photos."""
    try:
        return _view(service, service.give_up(device, session_id))
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
