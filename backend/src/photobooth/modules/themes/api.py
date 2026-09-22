"""Theme routes under /api/admin/themes (paired device + admin session)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import provide, require_device
from photobooth.modules.themes.domain import ThemeSourceError
from photobooth.modules.themes.schemas import (
    ExtractBody,
    ExtractedTheme,
    MainColoursBody,
    MainColoursResponse,
    ThemeCatalogResponse,
)
from photobooth.modules.themes.service import ThemeService

router = APIRouter(
    prefix="/api/admin/themes",
    tags=["admin-themes"],
    dependencies=[Depends(require_device), Depends(require_admin)],
)

Service = Annotated[ThemeService, Depends(provide(ThemeService))]


@router.get("", response_model=ThemeCatalogResponse)
def theme_catalog(service: Service) -> ThemeCatalogResponse:
    """Every semantic colour token, the contrast rules and the preset palettes."""
    return ThemeCatalogResponse.of(service.presets(), service.default_preset())


@router.post("/extract", response_model=ExtractedTheme)
async def extract_theme(body: ExtractBody, service: Service) -> ExtractedTheme:
    """A complete accessible theme from the dominant colours of an uploaded background image.

    Runs locally; the image is read, never changed. Nothing is saved until the profile is saved.
    """
    try:
        theme = await run_in_threadpool(service.extract, body.background_asset_id)
    except ThemeSourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return ExtractedTheme.of(theme)


@router.post("/main-colours", response_model=MainColoursResponse)
def theme_main_colours(body: MainColoursBody, service: Service) -> MainColoursResponse:
    """Regenerate the related colours (shades, links, borders, focus, labels) from the Button
    and Text colours. Nothing is saved until the profile is saved."""
    try:
        tokens, button, text = service.main_colours(dict(body.tokens), body.button, body.text)
    except ThemeSourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return MainColoursResponse(tokens=tokens, button=button, text=text)
