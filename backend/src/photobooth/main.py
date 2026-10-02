"""ASGI application factories for the two listeners.

- Kiosk app: booth + admin + API + built UI. Bound to 127.0.0.1 only. Host allowlist.
- Delivery app: guest-facing LAN listener. Mounts ONLY delivery routes (/d/...).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response as StarletteResponse

from photobooth import __version__
from photobooth.core.config import KIOSK_ALLOWED_HOSTS
from photobooth.core.host_guard import BodySizeLimitMiddleware, HostAllowlistMiddleware
from photobooth.core.web import REGISTRY_STATE_KEY, ServiceRegistry
from photobooth.modules.activity.api import AdminAudit, registry_service
from photobooth.modules.activity.api import router as activity_router
from photobooth.modules.assets.api import router as assets_router
from photobooth.modules.auth.api import router as admin_auth_router
from photobooth.modules.booth.admin_api import router as booth_test_menu_router
from photobooth.modules.booth.api import router as booth_frames_router
from photobooth.modules.decorations.api import router as decorations_router
from photobooth.modules.delivery.api import router as delivery_router
from photobooth.modules.event_profiles.api import router as profiles_router
from photobooth.modules.frames.api import router as frames_router
from photobooth.modules.kiosk.api import booth_router, pairing_router, status_router
from photobooth.modules.rendering.api import router as rendering_router
from photobooth.modules.retention.api import router as retention_router
from photobooth.modules.sessions.admin_api import router as booth_test_sessions_router
from photobooth.modules.sessions.api import router as booth_sessions_router
from photobooth.modules.system.admin_api import router as system_admin_router
from photobooth.modules.system.api import router as system_router
from photobooth.modules.templates.api import router as templates_router
from photobooth.modules.themes.api import router as themes_router

log = logging.getLogger("photobooth.delivery")


@dataclass(frozen=True)
class KioskAppOptions:
    allowed_hosts: tuple[str, ...] = KIOSK_ALLOWED_HOSTS
    max_request_bytes: int = 15 * 1024 * 1024
    frontend_dist: Path | None = None


def create_kiosk_app(registry: ServiceRegistry, options: KioskAppOptions) -> FastAPI:
    app = FastAPI(
        title="Photobooth kiosk API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    setattr(app.state, REGISTRY_STATE_KEY, registry)
    app.include_router(system_router)
    app.include_router(status_router)
    app.include_router(pairing_router)
    app.include_router(booth_router)
    app.include_router(templates_router)
    app.include_router(rendering_router)
    app.include_router(admin_auth_router)
    app.include_router(assets_router)
    app.include_router(profiles_router)
    app.include_router(frames_router)
    app.include_router(themes_router)
    app.include_router(booth_frames_router)
    app.include_router(booth_sessions_router)
    app.include_router(decorations_router)
    app.include_router(activity_router)
    app.include_router(retention_router)
    app.include_router(system_admin_router)
    # "Test booth" is served under one prefix by the two modules it belongs to.
    app.include_router(booth_test_menu_router)
    app.include_router(booth_test_sessions_router)

    if options.frontend_dist is not None and (options.frontend_dist / "index.html").is_file():
        _mount_spa(app, options.frontend_dist)

    # Outermost first: Host check runs before anything else, then the body cap.
    # Innermost: it sees which admin route answered, after the change has succeeded.
    app.add_middleware(AdminAudit, service=registry_service)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=options.max_request_bytes)
    app.add_middleware(HostAllowlistMiddleware, allowed_hosts=options.allowed_hosts)
    return app


def _mount_spa(app: FastAPI, dist: Path) -> None:
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    index = dist / "index.html"
    dist_real = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "kiosk/")):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist_real in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


_DELIVERY_HEADERS = {
    # The token is in the address: it must never travel to another site in a Referer header,
    # land in a shared cache, or be indexed.
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Robots-Tag": "noindex, nofollow",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def create_delivery_app(registry: ServiceRegistry) -> FastAPI:
    """Guest listener. Nothing but delivery routes may ever be mounted here."""
    app = FastAPI(
        title="Photobooth delivery",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    setattr(app.state, REGISTRY_STATE_KEY, registry)

    @app.get("/d/_alive", response_class=PlainTextResponse, include_in_schema=False)
    def alive() -> str:
        return "ok"

    app.include_router(delivery_router)

    @app.exception_handler(StarletteHTTPException)
    async def uniform_not_found(
        _request: Request, exc: StarletteHTTPException
    ) -> PlainTextResponse:
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            # Being told to slow down reveals nothing about any link.
            return PlainTextResponse(
                "too many requests",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers=dict(exc.headers or {}),
            )
        # Uniform response: never reveal whether a path, method or token exists.
        return PlainTextResponse("not found", status_code=status.HTTP_404_NOT_FOUND)

    @app.exception_handler(RequestValidationError)
    async def uniform_invalid(_request: Request, _exc: RequestValidationError) -> PlainTextResponse:
        return PlainTextResponse("not found", status_code=status.HTTP_404_NOT_FOUND)

    @app.middleware("http")
    async def guest_headers(
        request: Request, call_next: Callable[[Request], Awaitable[StarletteResponse]]
    ) -> StarletteResponse:
        try:
            response = await call_next(request)
        except Exception as exc:
            # Caught here, not by a server error handler: such a handler answers AND re-raises,
            # so the server would log the traceback, whose message may carry the link's token.
            # Only the kind of failure is logged; the request's path never is.
            log.error("delivery request failed: %s", type(exc).__name__)
            response = PlainTextResponse("not found", status_code=status.HTTP_404_NOT_FOUND)
        for name, value in _DELIVERY_HEADERS.items():
            response.headers.setdefault(name, value)
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'")
        return response

    return app
