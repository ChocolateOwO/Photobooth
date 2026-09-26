"""FastAPI glue: typed service lookup from the composition root and device authentication."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, cast

from fastapi import HTTPException, Request, status

from photobooth.core.kiosk_pairing import (
    LAUNCHER_HEADER,
    DeviceCredentialRegistry,
    LauncherCredential,
)

REGISTRY_STATE_KEY = "service_registry"
DEVICE_KEY_HEADER = "X-Photobooth-Device-Key"
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
    - Unsafe methods: exact Origin allowlist and the device key header issued with this cookie
      (403). Cookies are shared across ports of 127.0.0.1, so any local server the browser visits
      can capture the cookie; the key lives only in the UI origin storage and no endpoint returns
      it, so a captured cookie (with any forged Origin) can not mutate.
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
    if not credentials.verify_key(device, request.headers.get(DEVICE_KEY_HEADER)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="device key invalid")


def device_identity(request: Request) -> str:
    """A stable name for the paired device, derived from its cookie.

    Sessions belong to the device that started them, so a second browser can not read or continue
    somebody else's visit. The cookie itself is a secret and is never stored: only this digest is.
    """
    registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
    cookie = request.cookies.get(registry.get(DeviceCookieSettings).cookie_name)
    if cookie is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="device not paired")
    return hashlib.sha256(cookie.encode()).hexdigest()[:32]


def require_launcher(request: Request) -> None:
    """Dependency for launcher-only mutations (pairing-code rotation)."""
    registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
    if not registry.get(LauncherCredential).verify(request.headers.get(LAUNCHER_HEADER)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="launcher credential required"
        )


def is_device_paired(request: Request) -> bool:
    """Whether the request carries a valid device cookie (reveals no secret)."""
    registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
    cookie = registry.get(DeviceCookieSettings).cookie_name
    return registry.get(DeviceCredentialRegistry).verify(request.cookies.get(cookie))
