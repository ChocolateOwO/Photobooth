"""Admin authentication gate for routes (framework glue; the policy lives in the auth module).

Every admin route already requires the paired device (cookie; and for mutations Origin + device
key). On top of that it requires a valid admin session cookie bound to that same device, and every
admin mutation must carry the per-session CSRF token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import HTTPException, Request, status

from photobooth.core.web import (
    REGISTRY_STATE_KEY,
    SAFE_METHODS,
    DeviceCookieSettings,
    ServiceRegistry,
)

ADMIN_CSRF_HEADER = "X-Photobooth-Admin-CSRF"


@dataclass(frozen=True)
class AdminPrincipal:
    user_id: str
    username: str


class AdminCookieSettings:
    """Instance-scoped admin session cookie name (Dummy and Main never share it)."""

    def __init__(self, cookie_name: str) -> None:
        self.cookie_name = cookie_name


class AdminAuthenticator:
    """Port implemented by the auth module. A plain base class (not an ABC) so the composition
    root can register it by type; the default denies everything."""

    def authenticate(
        self, session_token: str | None, device_token: str | None
    ) -> AdminPrincipal | None:
        """Principal for a live, unexpired session bound to this device, else None."""
        return None

    def verify_csrf(self, session_token: str | None, csrf_token: str | None) -> bool:
        return False


def require_admin(request: Request) -> AdminPrincipal:
    registry = cast(ServiceRegistry, getattr(request.app.state, REGISTRY_STATE_KEY))
    device_cookie = registry.get(DeviceCookieSettings).cookie_name
    admin_cookie = registry.get(AdminCookieSettings).cookie_name
    authenticator = registry.get(AdminAuthenticator)
    session_token = request.cookies.get(admin_cookie)
    principal = authenticator.authenticate(session_token, request.cookies.get(device_cookie))
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin login required")
    if request.method not in SAFE_METHODS and not authenticator.verify_csrf(
        session_token, request.headers.get(ADMIN_CSRF_HEADER)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin csrf token invalid"
        )
    return principal
