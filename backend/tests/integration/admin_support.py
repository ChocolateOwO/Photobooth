"""Helpers for admin API tests: pair the kiosk device, create the admin and log in."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from photobooth.container import Container

ORIGIN = "http://127.0.0.1:18111"
KEY_HEADER = "X-Photobooth-Device-Key"
CSRF_HEADER = "X-Photobooth-Admin-CSRF"
USERNAME = "admin"
PASSWORD = "correct horse battery staple"


def pair(client: TestClient, container: Container) -> str:
    token = container.launcher.path.read_text(encoding="utf-8")
    rotated = client.post("/kiosk/pairing-code/rotate", headers={"X-Photobooth-Launcher": token})
    assert rotated.status_code == 204
    code = container.pairing_store.path.read_text(encoding="utf-8")
    response = client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
    return response.headers["location"].removeprefix("/#pair-key=")


def adopt_device(client: TestClient, container: Container) -> str:
    """Issue a paired device directly (pairing-code rotation is rate limited)."""
    token, key = container.device_credentials.issue()
    client.cookies.set(container.settings.device_cookie_name, token)
    return key


def device_headers(key: str) -> dict[str, str]:
    return {"Origin": ORIGIN, KEY_HEADER: key}


def login(
    client: TestClient,
    container: Container,
    *,
    create_user: bool = True,
    password: str = PASSWORD,
    key: str | None = None,
) -> dict[str, str]:
    """Pair, log in and return the full header set for admin mutations."""
    if create_user:
        container.auth_service.set_password(USERNAME, PASSWORD)
    if key is None:
        key = pair(client, container)
    response = client.post(
        "/api/admin/auth/login",
        json={"username": USERNAME, "password": password},
        headers=device_headers(key),
    )
    assert response.status_code == 200, response.text
    return {**device_headers(key), CSRF_HEADER: response.json()["csrf_token"]}


def png(
    size: tuple[int, int] = (64, 64), color: tuple[int, int, int, int] = (1, 2, 3, 255)
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def jpeg(size: tuple[int, int] = (320, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 100, 50)).save(buffer, "JPEG")
    return buffer.getvalue()
