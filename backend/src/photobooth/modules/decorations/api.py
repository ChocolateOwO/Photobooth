"""Participant decoration routes under /api/booth/decorations (paired kiosk device).

- GET /api/booth/decorations                       the filters and stickers the booth offers
- GET /api/booth/decorations/stickers/{key}.png    one sticker (the very file the server pastes)

A guest's chosen decoration travels with the render request of their visit
(POST /api/booth/sessions/{id}/render), so it lives with the session routes, not here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from photobooth.core.web import provide, require_device
from photobooth.modules.decorations.domain import DecorationError
from photobooth.modules.decorations.schemas import DecorationCatalogResponse
from photobooth.modules.decorations.service import DecorationService

router = APIRouter(
    prefix="/api/booth/decorations", tags=["booth"], dependencies=[Depends(require_device)]
)

Service = Annotated[DecorationService, Depends(provide(DecorationService))]
StickerKey = Annotated[str, Path(pattern=r"^[a-z0-9_]{1,32}$")]


@router.get("", response_model=DecorationCatalogResponse)
def catalog(service: Service, response: Response) -> DecorationCatalogResponse:
    """The filters (with the colour matrices the server applies) and the stickers on offer."""
    response.headers["Cache-Control"] = "no-store"
    return DecorationCatalogResponse.of(service.catalog())


@router.get(
    "/stickers/{key}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def sticker(key: StickerKey, service: Service) -> Response:
    try:
        data = service.sticker_png(key)
    except DecorationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
