"""TV screen routes.

- GET  /tv                                 a page on the TV: type the six-digit code from Admin
- GET  /tv/pair?code=123456                pair the TV: device cookie + redirect /#pair-key=...
- GET  /api/booth/camera/frame.jpg         newest picture of the chosen PC camera (paired booth)
- GET  /api/admin/screen                   TV address and the chosen PC camera (admin)
- GET  /api/admin/screen/cameras           this PC's cameras (admin)
- PUT  /api/admin/screen/camera            choose the camera the TV booth photographs with (admin)
- GET  /api/admin/screen/cameras/{i}.jpg   a still from one camera, to tell them apart (admin)
- POST /api/admin/screen/tv-code           a new six-digit TV pairing code (admin)
"""

from __future__ import annotations

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import DeviceCookieSettings, provide, require_device
from photobooth.modules.screen.domain import CameraUnavailableError, TvAddress
from photobooth.modules.screen.service import PcCameraService, TvPairingService

Cameras = Annotated[PcCameraService, Depends(provide(PcCameraService))]
Pairing = Annotated[TvPairingService, Depends(provide(TvPairingService))]
CookieSettings = Annotated[DeviceCookieSettings, Depends(provide(DeviceCookieSettings))]


Address = Annotated[TvAddress, Depends(provide(TvAddress))]

tv_router = APIRouter(tags=["screen"])
booth_camera_router = APIRouter(
    prefix="/api/booth/camera", tags=["screen"], dependencies=[Depends(require_device)]
)
admin_router = APIRouter(
    prefix="/api/admin/screen",
    tags=["admin-screen"],
    dependencies=[Depends(require_device), Depends(require_admin)],
)

_NO_STORE = {"Cache-Control": "no-store"}
# Sharp enough for a 4K TV's live picture, small enough for Wi-Fi at about ten pictures a second.
PREVIEW_WIDTH = 1280


def _jpeg(data: bytes) -> Response:
    return Response(content=data, media_type="image/jpeg", headers=_NO_STORE)


def _tv_page(message: str = "") -> str:
    note = f'<p class="note">{escape(message)}</p>' if message else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect this TV</title>
<style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#111;color:#f4f4f4;
font:24px/1.4 system-ui,sans-serif}}
form{{display:grid;gap:24px;text-align:center;padding:32px}}
input{{font-size:56px;letter-spacing:12px;text-align:center;width:8ch;padding:12px;
border:2px solid #666;border-radius:12px;background:#222;color:#fff}}
button{{font-size:32px;padding:16px 48px;border:0;border-radius:12px;background:#4f8cff;color:#fff}}
.note{{color:#ffb4a8}}
</style></head><body>
<form method="get" action="/tv/pair">
<h1>Connect this TV to the photobooth</h1>
<p>In Admin on the booth PC, open Test booth and press "Show TV code".</p>
{note}
<input name="code" inputmode="numeric" pattern="[0-9]{{6}}" maxlength="6" autocomplete="off"
 autofocus required aria-label="Six-digit code">
<button type="submit">Connect</button>
</form></body></html>"""


@tv_router.get("/tv", include_in_schema=False, response_class=HTMLResponse)
def tv_page() -> HTMLResponse:
    return HTMLResponse(_tv_page(), headers=_NO_STORE)


@tv_router.get("/tv/pair", include_in_schema=False, response_model=None)
def tv_pair(
    pairing: Pairing,
    cookie: CookieSettings,
    code: Annotated[str | None, Query(max_length=16)] = None,
) -> Response:
    issued = pairing.consume(code)
    if issued is None:
        return HTMLResponse(
            _tv_page("That code did not work. Show a new code in Admin and try again."),
            status_code=status.HTTP_403_FORBIDDEN,
            headers=_NO_STORE,
        )
    credential, key = issued
    # As /kiosk/pair: the key travels only in the fragment, which browsers never send to servers.
    response = RedirectResponse(url=f"/booth#pair-key={key}", status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(cookie.cookie_name, credential, httponly=True, samesite="strict", path="/")
    return response


@booth_camera_router.get("/frame.jpg", response_class=Response)
def booth_frame(cameras: Cameras, preview: Annotated[bool, Query()] = False) -> Response:
    try:
        return _jpeg(cameras.frame(PREVIEW_WIDTH if preview else None))
    except CameraUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "camera unavailable") from exc


class PcCameraResponse(BaseModel):
    index: int
    label: str


class ScreenResponse(BaseModel):
    tv_url: str | None
    camera_index: int | None


class CameraChoice(BaseModel):
    index: int | None = Field(default=None, ge=0, le=9)


class TvCodeResponse(BaseModel):
    code: str
    expires_in_seconds: int
    tv_url: str | None


@admin_router.get("", response_model=ScreenResponse)
def screen(cameras: Cameras, address: Address, response: Response) -> ScreenResponse:
    response.headers["Cache-Control"] = "no-store"
    return ScreenResponse(tv_url=address.url, camera_index=cameras.chosen())


@admin_router.get("/cameras", response_model=list[PcCameraResponse])
def list_cameras(cameras: Cameras, response: Response) -> list[PcCameraResponse]:
    response.headers["Cache-Control"] = "no-store"
    return [PcCameraResponse(index=c.index, label=c.label) for c in cameras.cameras()]


@admin_router.put("/camera", response_model=ScreenResponse)
def choose_camera(body: CameraChoice, cameras: Cameras, address: Address) -> ScreenResponse:
    cameras.choose(body.index)
    return ScreenResponse(tv_url=address.url, camera_index=cameras.chosen())


@admin_router.get("/cameras/{index}.jpg", response_class=Response)
def camera_still(index: int, cameras: Cameras) -> Response:
    try:
        return _jpeg(cameras.preview(index, PREVIEW_WIDTH))
    except CameraUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "camera unavailable") from exc


@admin_router.post("/tv-code", response_model=TvCodeResponse)
def tv_code(pairing: Pairing, address: Address, response: Response) -> TvCodeResponse:
    response.headers["Cache-Control"] = "no-store"
    code, ttl = pairing.new_code()
    return TvCodeResponse(code=code, expires_in_seconds=ttl, tv_url=address.url)
