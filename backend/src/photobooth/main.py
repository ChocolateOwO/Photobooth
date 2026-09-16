"""ASGI application factories for the two listeners.

- Kiosk app: booth + admin + API + built UI. Bound to 127.0.0.1 only. Host allowlist.
- Delivery app: guest-facing LAN listener. Mounts ONLY delivery routes (Phase 1: /d/_alive).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from photobooth import __version__
from photobooth.core.config import KIOSK_ALLOWED_HOSTS
from photobooth.core.host_guard import BodySizeLimitMiddleware, HostAllowlistMiddleware
from photobooth.core.web import REGISTRY_STATE_KEY, ServiceRegistry
from photobooth.modules.kiosk.api import booth_router, pairing_router, status_router
from photobooth.modules.system.api import router as system_router


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

    if options.frontend_dist is not None and (options.frontend_dist / "index.html").is_file():
        _mount_spa(app, options.frontend_dist)

    # Outermost first: Host check runs before anything else, then the body cap.
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


def create_delivery_app() -> FastAPI:
    """Guest listener. Nothing but delivery routes may ever be mounted here."""
    app = FastAPI(
        title="Photobooth delivery",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/d/_alive", response_class=PlainTextResponse, include_in_schema=False)
    def alive() -> str:
        return "ok"

    @app.exception_handler(StarletteHTTPException)
    async def uniform_not_found(
        _request: Request, _exc: StarletteHTTPException
    ) -> PlainTextResponse:
        # Uniform response: never reveal whether a path, method or token exists.
        return PlainTextResponse("not found", status_code=status.HTTP_404_NOT_FOUND)

    return app
