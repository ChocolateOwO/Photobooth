"""The booth screens of a saved profile, for Admin "Test booth" (paired device + admin session).

- GET /api/admin/booth-test/menu/{profile_id}   that profile's booth screens, read-only

Reading a profile this way never activates it and never changes it. Starting and clearing the
test visits themselves belongs to the sessions module, which owns its own routes under the same
prefix, so neither module has to reach into the other.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import provide, require_device
from photobooth.modules.booth.domain import NoActiveEventError
from photobooth.modules.booth.schemas import FrameMenuResponse
from photobooth.modules.booth.service import BoothService

router = APIRouter(
    prefix="/api/admin/booth-test",
    tags=["admin-booth-test"],
    dependencies=[Depends(require_device), Depends(require_admin)],
)

Service = Annotated[BoothService, Depends(provide(BoothService))]
ProfileId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


@router.get("/menu/{profile_id}", response_model=FrameMenuResponse)
def test_menu(profile_id: ProfileId, booth: Service) -> FrameMenuResponse:
    """The booth screens of a saved profile, exactly as a guest would see them."""
    try:
        return FrameMenuResponse.of(booth.menu(profile_id))
    except NoActiveEventError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
