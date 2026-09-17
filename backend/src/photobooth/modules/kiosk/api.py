"""Kiosk routes.

- GET  /kiosk/pair?code=...          consume one-time code, set device cookie, redirect to
                                     /#pair-key=<device key> (fragment: never sent to servers)
- POST /kiosk/pairing-code/rotate    launcher-only (X-Photobooth-Launcher); publish a new code to
                                     the runtime file (code not returned)
- GET  /api/kiosk/status             {"paired": bool} (no secret)
- POST /api/booth/ping               device mutation stub: cookie + Origin allowlist + device key
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from photobooth.core.web import (
    DeviceCookieSettings,
    is_device_paired,
    provide,
    require_device,
    require_launcher,
)
from photobooth.modules.kiosk.domain import PairingOutcome, RotationRejectedError
from photobooth.modules.kiosk.service import KioskPairingService

Service = Annotated[KioskPairingService, Depends(provide(KioskPairingService))]
CookieSettings = Annotated[DeviceCookieSettings, Depends(provide(DeviceCookieSettings))]


class KioskStatusResponse(BaseModel):
    paired: bool


class PingResponse(BaseModel):
    ok: bool


pairing_router = APIRouter(tags=["kiosk"])
status_router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])
# Every booth route is device-authenticated at router level (route access matrix).
booth_router = APIRouter(
    prefix="/api/booth", tags=["booth"], dependencies=[Depends(require_device)]
)


@pairing_router.get("/kiosk/pair", include_in_schema=False)
def pair(
    service: Service,
    cookie: CookieSettings,
    code: Annotated[str | None, Query(max_length=128)] = None,
) -> RedirectResponse:
    result = service.pair(code)
    if (
        result.outcome is not PairingOutcome.PAIRED
        or result.device_credential is None
        or result.device_key is None
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="pairing rejected")
    # The key travels only in the fragment of this redirect to the UI origin that followed the
    # launcher pairing URL; browsers never send fragments to servers.
    response = RedirectResponse(
        url=f"/#pair-key={result.device_key}", status_code=status.HTTP_303_SEE_OTHER
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(
        cookie.cookie_name,
        result.device_credential,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response


@pairing_router.post(
    "/kiosk/pairing-code/rotate",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_launcher)],
)
def rotate_pairing_code(service: Service) -> None:
    try:
        service.rotate_code()
    except RotationRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rotate again later"
        ) from exc


@status_router.get("/status", response_model=KioskStatusResponse)
def kiosk_status(request: Request, response: Response) -> KioskStatusResponse:
    response.headers["Cache-Control"] = "no-store"
    return KioskStatusResponse(paired=is_device_paired(request))


@booth_router.post("/ping", response_model=PingResponse)
def booth_ping() -> PingResponse:
    return PingResponse(ok=True)
