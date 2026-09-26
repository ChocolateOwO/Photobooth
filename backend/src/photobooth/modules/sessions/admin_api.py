"""Admin "Test booth" routes under /api/admin/booth-test (paired device + admin session).

- GET  /api/admin/booth-test/menu/{profile_id}   that saved profile's booth screens, read-only
- POST /api/admin/booth-test/sessions            start a test visit on a saved profile
- POST /api/admin/booth-test/cleanup             clear away finished or forgotten test visits

Testing never activates or changes a profile, and a test visit is scratch data: it is removed
when the organizer leaves the test, and stale ones are swept. A guest's visit is never touched.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import device_identity, provide, require_device
from photobooth.modules.booth.domain import NoActiveEventError
from photobooth.modules.booth.schemas import FrameMenuResponse
from photobooth.modules.booth.service import BoothService
from photobooth.modules.sessions.domain import (
    EligibilityRefusedError,
    IdempotencyReuseError,
)
from photobooth.modules.sessions.domain import (
    NoActiveEventError as NoProfileError,
)
from photobooth.modules.sessions.schemas import BoothSessionResponse, StartTestBody
from photobooth.modules.sessions.service import BoothSessionService

router = APIRouter(
    prefix="/api/admin/booth-test",
    tags=["admin-booth-test"],
    dependencies=[Depends(require_device), Depends(require_admin)],
)

Booth = Annotated[BoothService, Depends(provide(BoothService))]
Sessions = Annotated[BoothSessionService, Depends(provide(BoothSessionService))]
Device = Annotated[str, Depends(device_identity)]
ProfileId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


@router.get("/menu/{profile_id}", response_model=FrameMenuResponse)
def test_menu(profile_id: ProfileId, booth: Booth) -> FrameMenuResponse:
    """The booth screens of a saved profile, exactly as a guest would see them."""
    try:
        return FrameMenuResponse.of(booth.menu(profile_id))
    except NoActiveEventError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/sessions", response_model=BoothSessionResponse, status_code=status.HTTP_201_CREATED)
def start_test(body: StartTestBody, sessions: Sessions, device: Device) -> BoothSessionResponse:
    """Start a test visit on that profile. It never becomes the active event."""
    try:
        session = sessions.start(device, body.idempotency_key, body.profile_id, is_test=True)
    except NoProfileError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EligibilityRefusedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IdempotencyReuseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return BoothSessionResponse.of(session, sessions.progress(session.id))


@router.post("/cleanup", status_code=status.HTTP_204_NO_CONTENT)
def clear_tests(sessions: Sessions) -> None:
    """Clear away test visits that are over or were left behind. Guests' visits are untouched."""
    sessions.clear_old_tests(keep_for_seconds=0)
