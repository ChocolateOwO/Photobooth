"""Admin authentication: Argon2 login, device-bound sessions, CSRF, throttling, logout."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher as Argon2
from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.main import KioskAppOptions, create_kiosk_app
from photobooth.modules.auth.domain import (
    LoginThrottle,
    LoginThrottledError,
    PasswordPolicyError,
)
from photobooth.modules.auth.hasher import Argon2PasswordHasher
from photobooth.modules.auth.repository import SqlAdminUserRepository
from photobooth.modules.auth.service import (
    SESSION_ABSOLUTE_SECONDS,
    SESSION_IDLE_SECONDS,
    AuthService,
)
from photobooth.modules.auth.sessions import InMemoryAdminSessionStore
from tests.integration.admin_support import (
    CSRF_HEADER,
    PASSWORD,
    USERNAME,
    adopt_device,
    device_headers,
    login,
    pair,
)

COOKIE = "pb_admin_dummy"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_password_is_stored_as_argon2id_and_never_plain(container: Container) -> None:
    container.auth_service.set_password("Admin", PASSWORD)
    stored = SqlAdminUserRepository(container.engine).get_by_username("admin")
    assert stored is not None
    assert stored.password_hash.startswith("$argon2id$")
    assert PASSWORD not in stored.password_hash


@pytest.mark.parametrize(
    ("username", "password"),
    [("admin", "short"), ("admin", "x" * 257), ("a", PASSWORD), ("bad name", PASSWORD)],
)
def test_password_policy(container: Container, username: str, password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        container.auth_service.set_password(username, password)
    with pytest.raises(PasswordPolicyError):
        container.auth_service.set_password("adminuser", "adminuser")


def test_login_sets_http_only_strict_cookie_and_returns_csrf(
    kiosk_client: TestClient, container: Container
) -> None:
    container.auth_service.set_password(USERNAME, PASSWORD)
    key = pair(kiosk_client, container)
    response = kiosk_client.post(
        "/api/admin/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        headers=device_headers(key),
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api/admin" in cookie
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["username"] == USERNAME and len(body["csrf_token"]) >= 40
    assert body["expires_in_seconds"] == SESSION_IDLE_SECONDS

    session = kiosk_client.get("/api/admin/auth/session")
    assert session.status_code == 200
    assert session.json()["csrf_token"] == body["csrf_token"]


def test_login_requires_paired_device_origin_and_key(
    kiosk_client: TestClient, container: Container
) -> None:
    container.auth_service.set_password(USERNAME, PASSWORD)
    creds = {"username": USERNAME, "password": PASSWORD}
    assert kiosk_client.post("/api/admin/auth/login", json=creds).status_code == 401
    key = pair(kiosk_client, container)
    assert kiosk_client.post("/api/admin/auth/login", json=creds).status_code == 403
    bad_origin = {**device_headers(key), "Origin": "http://127.0.0.1:3000"}
    assert (
        kiosk_client.post("/api/admin/auth/login", json=creds, headers=bad_origin).status_code
        == 403
    )


def test_wrong_password_and_unknown_user_are_indistinguishable(
    kiosk_client: TestClient, container: Container
) -> None:
    container.auth_service.set_password(USERNAME, PASSWORD)
    headers = device_headers(pair(kiosk_client, container))
    wrong = kiosk_client.post(
        "/api/admin/auth/login",
        json={"username": USERNAME, "password": "nope-nope-nope"},
        headers=headers,
    )
    unknown = kiosk_client.post(
        "/api/admin/auth/login", json={"username": "ghost", "password": PASSWORD}, headers=headers
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "set-cookie" not in wrong.headers


def test_admin_routes_require_session_and_csrf(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    no_csrf = {k: v for k, v in headers.items() if k != CSRF_HEADER}
    body = {"name": "Event", "title": "Hi", "enabled_layouts": ["strip_2x6"]}

    assert kiosk_client.post("/api/admin/profiles", json=body, headers=no_csrf).status_code == 403
    forged = {**no_csrf, CSRF_HEADER: "forged"}
    assert kiosk_client.post("/api/admin/profiles", json=body, headers=forged).status_code == 403
    assert kiosk_client.post("/api/admin/profiles", json=body, headers=headers).status_code == 201

    kiosk_client.cookies.delete(COOKIE, path="/api/admin")
    kiosk_client.cookies.delete(COOKIE)
    assert kiosk_client.get("/api/admin/profiles").status_code == 401
    assert kiosk_client.post("/api/admin/profiles", json=body, headers=headers).status_code == 401


def test_session_is_bound_to_the_device_that_logged_in(
    kiosk_client: TestClient, container: Container
) -> None:
    login(kiosk_client, container)
    session_cookie = next(c for c in kiosk_client.cookies.jar if c.name == COOKIE).value

    app = create_kiosk_app(container.registry, KioskAppOptions())
    with TestClient(app, base_url="http://127.0.0.1:18111") as other:
        adopt_device(other, container)  # a second, legitimately paired device
        other.cookies.set(COOKIE, session_cookie, path="/api/admin")
        assert other.get("/api/admin/auth/session").status_code == 401
        assert other.get("/api/admin/profiles").status_code == 401


def test_logout_revokes_the_session(kiosk_client: TestClient, container: Container) -> None:
    headers = login(kiosk_client, container)
    session_cookie = next(c for c in kiosk_client.cookies.jar if c.name == COOKIE).value
    assert kiosk_client.post("/api/admin/auth/logout", headers=headers).status_code == 204
    kiosk_client.cookies.set(COOKIE, session_cookie, path="/api/admin")  # replay the old cookie
    assert kiosk_client.get("/api/admin/auth/session").status_code == 401


def test_login_throttle_returns_429_with_retry_after(
    kiosk_client: TestClient, container: Container
) -> None:
    container.auth_service.set_password(USERNAME, PASSWORD)
    headers = device_headers(pair(kiosk_client, container))
    bad = {"username": USERNAME, "password": "wrong-password-xx"}
    for _ in range(5):
        assert (
            kiosk_client.post("/api/admin/auth/login", json=bad, headers=headers).status_code == 401
        )
    good = {"username": USERNAME, "password": PASSWORD}
    locked = kiosk_client.post("/api/admin/auth/login", json=good, headers=headers)
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0


def test_restart_ends_sessions_but_keeps_the_admin_user(settings: AppSettings) -> None:
    from photobooth.core.migrations import Migrator

    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    try:
        with TestClient(
            create_kiosk_app(first.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        ) as c:
            login(c, first)
            cookie = next(x for x in c.cookies.jar if x.name == COOKIE).value
    finally:
        first.close()
    second = Container(settings)
    try:
        with TestClient(
            create_kiosk_app(second.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        ) as c:
            key = pair(c, second)
            c.cookies.set(COOKIE, cookie, path="/api/admin")
            assert c.get("/api/admin/auth/session").status_code == 401
            headers = login(c, second, create_user=False, key=key)
            assert headers[CSRF_HEADER]
    finally:
        second.close()


def _service(
    container: Container, clock: FakeClock, hasher: Argon2PasswordHasher | None = None
) -> AuthService:
    return AuthService(
        SqlAdminUserRepository(container.engine),
        hasher or Argon2PasswordHasher(),
        InMemoryAdminSessionStore(),
        LoginThrottle(clock),
        monotonic=clock,
        now=lambda: datetime.now(UTC),
    )


def test_idle_and_absolute_session_expiry(container: Container) -> None:
    clock = FakeClock()
    service = _service(container, clock)
    service.set_password(USERNAME, PASSWORD)

    idle = service.login(USERNAME, PASSWORD, "device-a")
    clock.now += SESSION_IDLE_SECONDS - 1
    assert service.session(idle.session_token, "device-a") is not None
    clock.now += SESSION_IDLE_SECONDS
    assert service.session(idle.session_token, "device-a") is None

    absolute = service.login(USERNAME, PASSWORD, "device-a")
    start = clock.now
    step = SESSION_IDLE_SECONDS - 100
    while clock.now + step < start + SESSION_ABSOLUTE_SECONDS:
        clock.now += step  # keep the session active
        assert service.session(absolute.session_token, "device-a") is not None
    clock.now = start + SESSION_ABSOLUTE_SECONDS
    assert service.session(absolute.session_token, "device-a") is None


def test_password_change_revokes_existing_sessions(container: Container) -> None:
    clock = FakeClock()
    service = _service(container, clock)
    service.set_password(USERNAME, PASSWORD)
    result = service.login(USERNAME, PASSWORD, "device-a")
    service.set_password(USERNAME, PASSWORD + "-new")
    assert service.session(result.session_token, "device-a") is None
    assert not service.verify_csrf(result.session_token, result.csrf_token)


def test_weak_hash_is_upgraded_on_login(container: Container) -> None:
    clock = FakeClock()
    weak = Argon2PasswordHasher(Argon2(time_cost=1, memory_cost=8, parallelism=1))
    _service(container, clock, weak).set_password(USERNAME, PASSWORD)
    repo = SqlAdminUserRepository(container.engine)
    before = repo.get_by_username(USERNAME)
    assert before is not None and "m=8," in before.password_hash

    _service(container, clock).login(USERNAME, PASSWORD, "device-a")
    after = repo.get_by_username(USERNAME)
    assert after is not None and after.password_hash != before.password_hash
    assert "m=8," not in after.password_hash and after.last_login_at is not None


def test_throttle_locks_per_user_and_globally() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(clock, max_failures=3, window_s=60, lockout_s=30)
    for _ in range(3):
        throttle.failure("admin")
    with pytest.raises(LoginThrottledError) as info:
        throttle.check("admin")
    assert 0 < info.value.retry_after_seconds <= 31
    throttle.check("other")
    clock.now += 31
    throttle.check("admin")
    # failures spread beyond the window never lock
    for _ in range(5):
        throttle.failure("slow")
        clock.now += 61
    throttle.check("slow")
