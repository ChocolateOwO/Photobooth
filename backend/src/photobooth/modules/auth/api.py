"""Admin auth routes under /api/admin/auth (kiosk listener; paired device required)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from photobooth.core.admin_gate import (
    AdminAuthenticator,
    AdminCookieSettings,
    AdminPrincipal,
    require_admin,
)
from photobooth.core.web import DeviceCookieSettings, provide, require_device
from photobooth.modules.auth.domain import InvalidCredentialsError, LoginThrottledError
from photobooth.modules.auth.service import SESSION_IDLE_SECONDS, AuthService

router = APIRouter(
    prefix="/api/admin/auth", tags=["admin-auth"], dependencies=[Depends(require_device)]
)

Service = Annotated[AuthService, Depends(provide(AuthService))]
AdminCookie = Annotated[AdminCookieSettings, Depends(provide(AdminCookieSettings))]
DeviceCookie = Annotated[DeviceCookieSettings, Depends(provide(DeviceCookieSettings))]
Admin = Annotated[AdminPrincipal, Depends(require_admin)]
COOKIE_PATH = "/api/admin"


class AdminAuthGate(AdminAuthenticator):
    """Adapts AuthService to the core admin gate used by every admin router."""

    def __init__(self, service: AuthService) -> None:
        self._service = service

    def authenticate(
        self, session_token: str | None, device_token: str | None
    ) -> AdminPrincipal | None:
        info = self._service.session(session_token, device_token)
        return (
            None if info is None else AdminPrincipal(user_id=info.user_id, username=info.username)
        )

    def verify_csrf(self, session_token: str | None, csrf_token: str | None) -> bool:
        return self._service.verify_csrf(session_token, csrf_token)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SessionResponse(BaseModel):
    username: str
    csrf_token: str
    expires_in_seconds: int


@router.post("/login", response_model=SessionResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: Service,
    admin_cookie: AdminCookie,
    device_cookie: DeviceCookie,
) -> SessionResponse:
    device_token = request.cookies.get(device_cookie.cookie_name, "")
    try:
        result = service.login(body.username, body.password, device_token)
    except LoginThrottledError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    info = service.session(result.session_token, device_token)
    if info is None:  # pragma: no cover - a just-created session is always valid
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    response.set_cookie(
        admin_cookie.cookie_name,
        result.session_token,
        httponly=True,
        samesite="strict",
        path=COOKIE_PATH,
    )
    # Who signed in, for the admin audit (never the password: request bodies are not logged).
    request.state.admin_principal = AdminPrincipal(user_id=info.user_id, username=info.username)
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse(
        username=result.username,
        csrf_token=result.csrf_token,
        expires_in_seconds=SESSION_IDLE_SECONDS,
    )


@router.get("/session", response_model=SessionResponse)
def current_session(
    _admin: Admin,
    request: Request,
    response: Response,
    service: Service,
    admin_cookie: AdminCookie,
    device_cookie: DeviceCookie,
) -> SessionResponse:
    info = service.session(
        request.cookies.get(admin_cookie.cookie_name),
        request.cookies.get(device_cookie.cookie_name),
    )
    if info is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin login required")
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse(
        username=info.username, csrf_token=info.csrf_token, expires_in_seconds=SESSION_IDLE_SECONDS
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    _admin: Admin, request: Request, response: Response, service: Service, admin_cookie: AdminCookie
) -> None:
    service.logout(request.cookies.get(admin_cookie.cookie_name))
    response.delete_cookie(
        admin_cookie.cookie_name, path=COOKIE_PATH, httponly=True, samesite="strict"
    )
