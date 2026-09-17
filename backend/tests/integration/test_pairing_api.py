from __future__ import annotations

import time

from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.main import KioskAppOptions, create_kiosk_app


def _launcher(container: Container) -> dict[str, str]:
    token = container.launcher.path.read_text(encoding="utf-8")
    return {"X-Photobooth-Launcher": token}


def _rotate_and_read(client: TestClient, container: Container) -> str:
    response = client.post("/kiosk/pairing-code/rotate", headers=_launcher(container))
    assert response.status_code == 204
    return container.pairing_store.path.read_text(encoding="utf-8")


def test_rotate_requires_launcher_credential(
    kiosk_client: TestClient, container: Container
) -> None:
    assert kiosk_client.post("/kiosk/pairing-code/rotate").status_code == 401
    wrong = {"X-Photobooth-Launcher": "forged"}
    assert kiosk_client.post("/kiosk/pairing-code/rotate", headers=wrong).status_code == 401
    assert not container.pairing_store.path.exists()


def test_launcher_token_published_to_runtime_and_cleared_on_close(container: Container) -> None:
    path = container.settings.runtime_dir / "launcher.token"
    assert len(path.read_text(encoding="utf-8")) >= 40
    container.close()
    assert not path.exists()


def test_rotate_does_not_return_code(kiosk_client: TestClient, container: Container) -> None:
    response = kiosk_client.post("/kiosk/pairing-code/rotate", headers=_launcher(container))
    assert response.status_code == 204
    assert response.content == b""
    assert container.pairing_store.path.is_file()


def test_rotate_is_rate_limited(kiosk_client: TestClient, container: Container) -> None:
    headers = _launcher(container)
    assert kiosk_client.post("/kiosk/pairing-code/rotate", headers=headers).status_code == 204
    assert kiosk_client.post("/kiosk/pairing-code/rotate", headers=headers).status_code == 429


def test_pairing_sets_strict_httponly_cookie_and_is_single_use(
    kiosk_client: TestClient, container: Container
) -> None:
    code = _rotate_and_read(kiosk_client, container)
    response = kiosk_client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/#pair-key=")
    assert len(location.removeprefix("/#pair-key=")) >= 43
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    set_cookie = response.headers["set-cookie"].lower()
    assert set_cookie.startswith("pb_device_dummy=")
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie

    kiosk_client.cookies.clear()
    reuse = kiosk_client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
    assert reuse.status_code == 403
    assert "set-cookie" not in reuse.headers


def test_pairing_rejects_missing_or_wrong_code(
    kiosk_client: TestClient, container: Container
) -> None:
    _rotate_and_read(kiosk_client, container)
    assert kiosk_client.get("/kiosk/pair", follow_redirects=False).status_code == 403
    assert kiosk_client.get("/kiosk/pair?code=guess", follow_redirects=False).status_code == 403


ORIGIN = {"Origin": "http://127.0.0.1:18111"}


KEY_HEADER = "X-Photobooth-Device-Key"


def _pair(client: TestClient, container: Container) -> str:
    """Pair and return the device key taken from the redirect fragment (as the UI does)."""
    code = _rotate_and_read(client, container)
    response = client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
    key = response.headers["location"].removeprefix("/#pair-key=")
    assert client.get("/api/kiosk/status").json() == {"paired": True}
    return key


def test_booth_mutation_requires_device_cookie(
    kiosk_client: TestClient, container: Container
) -> None:
    assert kiosk_client.post("/api/booth/ping").status_code == 401
    assert kiosk_client.get("/api/kiosk/status").json() == {"paired": False}

    key = _pair(kiosk_client, container)
    headers = {**ORIGIN, KEY_HEADER: key}
    assert kiosk_client.post("/api/booth/ping", headers=headers).json() == {"ok": True}
    assert kiosk_client.get("/api/kiosk/status").headers["cache-control"] == "no-store"


def test_paired_cookie_alone_cannot_mutate_without_origin_and_device_key(
    kiosk_client: TestClient, container: Container
) -> None:
    key = _pair(kiosk_client, container)
    ping = "/api/booth/ping"
    # No Origin (non-browser or stripped) -> 403
    assert kiosk_client.post(ping, headers={KEY_HEADER: key}).status_code == 403
    # Another local application on a different port (same-site, cross-origin) -> 403
    for origin in (
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:8121",
        "null",
        "http://evil.example",
    ):
        headers = {"Origin": origin, KEY_HEADER: key}
        assert kiosk_client.post(ping, headers=headers).status_code == 403, origin
    # Allowed origin but missing / wrong key -> 403
    assert kiosk_client.post(ping, headers=ORIGIN).status_code == 403
    assert kiosk_client.post(ping, headers={**ORIGIN, KEY_HEADER: "x" * 43}).status_code == 403
    # Allowed origin + key -> 200
    assert kiosk_client.post(ping, headers={**ORIGIN, KEY_HEADER: key}).status_code == 200


def test_captured_cookie_can_not_recover_key_or_mutate(
    kiosk_client: TestClient, container: Container
) -> None:
    """A local server that captured the HttpOnly cookie replays it directly (R20)."""
    _pair(kiosk_client, container)
    stolen = kiosk_client.cookies.get("pb_device_dummy")
    assert stolen

    app = create_kiosk_app(container.registry, KioskAppOptions())
    with TestClient(app, base_url="http://127.0.0.1:18111") as attacker:
        attacker.cookies.set("pb_device_dummy", stolen)
        # Every readable endpoint, with the stolen cookie, reveals no key material.
        for path in ("/api/kiosk/status", "/api/health", "/api/version", "/api/openapi.json"):
            body = attacker.get(path).text
            assert "key" not in body.lower() or path == "/api/openapi.json", path
        assert attacker.get("/api/kiosk/status").json() == {"paired": True}
        # Forged allowed Origin with no key, an empty key, or a cookie value as the key -> 403.
        for headers in (ORIGIN, {**ORIGIN, KEY_HEADER: ""}, {**ORIGIN, KEY_HEADER: stolen}):
            assert attacker.post("/api/booth/ping", headers=headers).status_code == 403


def test_device_key_is_bound_to_its_own_cookie(container: Container) -> None:
    registry = container.device_credentials
    token_a, key_a = registry.issue()
    token_b, key_b = registry.issue()
    assert key_a != key_b and token_a != key_a
    assert registry.verify_key(token_a, key_a)
    assert not registry.verify_key(token_a, key_b)
    assert not registry.verify_key(token_b, key_a)
    assert not registry.verify_key("forged", key_a)
    assert not registry.verify_key(token_a, None)


def test_forged_cookie_rejected(kiosk_client: TestClient) -> None:
    kiosk_client.cookies.set("pb_device_dummy", "forged-value")
    assert kiosk_client.post("/api/booth/ping").status_code == 401


def test_cookie_from_previous_server_start_rejected(container: Container) -> None:
    app = create_kiosk_app(container.registry, KioskAppOptions())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        code = _rotate_and_read(client, container)
        client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
        old_cookie = client.cookies.get("pb_device_dummy")
        assert old_cookie
    container.close()

    restarted = Container(container.settings)  # simulates a new process start
    try:
        assert not restarted.pairing_store.path.exists()
        app2 = create_kiosk_app(restarted.registry, KioskAppOptions())
        with TestClient(app2, base_url="http://127.0.0.1") as client2:
            client2.cookies.set("pb_device_dummy", old_cookie)
            assert client2.post("/api/booth/ping").status_code == 401
    finally:
        restarted.close()


def test_main_cookie_name_is_not_accepted_by_dummy(
    kiosk_client: TestClient, container: Container
) -> None:
    code = _rotate_and_read(kiosk_client, container)
    kiosk_client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
    value = kiosk_client.cookies.get("pb_device_dummy")
    kiosk_client.cookies.clear()
    kiosk_client.cookies.set("pb_device_main", value or "")
    assert kiosk_client.post("/api/booth/ping").status_code == 401


def test_health_and_version_readable_without_cookie(kiosk_client: TestClient) -> None:
    assert kiosk_client.get("/api/health").status_code == 200
    assert kiosk_client.get("/api/version").status_code == 200


def test_expired_code_rejected_via_api(container: Container) -> None:
    container.close()
    now = [time.monotonic()]
    clocked = Container(container.settings, clock=lambda: now[0])
    try:
        app = create_kiosk_app(clocked.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1") as client:
            code = _rotate_and_read(client, clocked)
            now[0] += 61
            response = client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
            assert response.status_code == 403
    finally:
        clocked.close()
