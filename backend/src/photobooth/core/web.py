"""FastAPI glue: typed service lookup from the composition root and device authentication."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from fastapi import HTTPException, Request, status

from photobooth.core.kiosk_pairing import DeviceCredentialRegistry

REGISTRY_STATE_KEY = "service_registry"


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
    """Name of the instance-scoped device cookie (Dummy and Main never share it)."""

    def __init__(self, cookie_name: str) -> None:
        self.cookie_name = cookie_name


def require_device(request: Request) -> None:
    """Dependency for every booth/admin route: the paired device cookie is mandatory."""
    registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
    cookie = registry.get(DeviceCookieSettings).cookie_name
    credentials = registry.get(DeviceCredentialRegistry)
    if not credentials.verify(request.cookies.get(cookie)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="device not paired")


def is_device_paired(request: Request) -> bool:
    registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
    cookie = registry.get(DeviceCookieSettings).cookie_name
    return registry.get(DeviceCredentialRegistry).verify(request.cookies.get(cookie))
