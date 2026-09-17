"""FastAPI glue: typed service lookup from the composition root and device authentication."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from fastapi import HTTPException, Request, status

from photobooth.core.kiosk_pairing import (
    LAUNCHER_HEADER,
    DeviceCredentialRegistry,
    LauncherCredential,
)

REGISTRY_STATE_KEY = "service_registry"
CSRF_HEADER = "X-Photobooth-CSRF"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ServiceRegistry:
    """Maps a service type to its instance. Filled only by the composition root."""

    def __init__(self) -> None:
        self._services: dict[type[Any], object] = {}

    def register[T](self, kind: type[T], instance: T) -> None:
        self._services[kind] = instance

    def get[T](self, kind: type[T]) -> T:
        try:
            return cast(T, self._services[kind])
        except KeyError as exc:
            raise LookupError(f"service not registered: {kind.__name__}") from exc


def provide[T](kind: type[T]) -> Callable[[Request], T]:
    """FastAPI dependency factory: `Depends(provide(SystemService))`."""

    def _dependency(request: Request) -> T:
        registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
        return registry.get(kind)

    _dependency.__name__ = f"provide_{kind.__name__}"
    return _dependency


class DeviceCookieSettings:
    """Instance-scoped device cookie name and the exact browser origins allowed to mutate."""

    def __init__(self, cookie_name: str, allowed_origins: frozenset[str] = frozenset()) -> None:
        self.cookie_name = cookie_name
        self.allowed_origins = allowed_origins


def require_device(request: Request) -> None:
    """Dependency for every booth/admin route.

    - Always: the paired device cookie (401).
    - Unsafe methods: exact Origin allowlist and CSRF header bound to the cookie (403). Cookies are
      shared across ports of 127.0.0.1 and SameSite treats other local ports as same-site, so the
      cookie alone does not prove the request came from this instance's UI.
    """
    registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
    settings = registry.get(DeviceCookieSettings)
    credentials = registry.get(DeviceCredentialRegistry)
    device = request.cookies.get(settings.cookie_name)
    if not credentials.verify(device):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="device not paired")
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None or origin not in settings.allowed_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin not allowed")
    if not credentials.verify_csrf(device, request.headers.get(CSRF_HEADER)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf token invalid")


def require_launcher(request: Request) -> None:
    """Dependency for launcher-only mutations (pairing-code rotation)."""
    registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
    if not registry.get(LauncherCredential).verify(request.headers.get(LAUNCHER_HEADER)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="launcher credential required"
        )


def device_csrf_token(request: Request) -> str | None:
    """CSRF token for the calling paired device, or None when not paired."""
    registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
    cookie = registry.get(DeviceCookieSettings).cookie_name
    return registry.get(DeviceCredentialRegistry).csrf_token_for(request.cookies.get(cookie))
