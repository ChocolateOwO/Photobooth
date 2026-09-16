from __future__ import annotations

import time

from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.main import KioskAppOptions, create_kiosk_app


def _rotate_and_read(client: TestClient, container: Container) -> str:
    assert client.post("/kiosk/pairing-code/rotate").status_code == 204
    return container.pairing_store.path.read_text(encoding="utf-8")


def test_rotate_does_not_return_code(kiosk_client: TestClient, container: Container) -> None:
    response = kiosk_client.post("/kiosk/pairing-code/rotate")
    assert response.status_code == 204
    assert response.content == b""
    assert container.pairing_store.path.is_file()


def test_rotate_is_rate_limited(kiosk_client: TestClient) -> None:
    assert kiosk_client.post("/kiosk/pairing-code/rotate").status_code == 204
    assert kiosk_client.post("/kiosk/pairing-code/rotate").status_code == 429


def test_pairing_sets_strict_httponly_cookie_and_is_single_use(
    kiosk_client: TestClient, container: Container
) -> None:
    code = _rotate_and_read(kiosk_client, container)
    response = kiosk_client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    set_cookie = response.headers["set-cookie"].lower()
    assert set_cookie.startswith("pb_device_dummy=")
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie

    kiosk_client.cookies.clear()
    reuse = kiosk_client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
    assert reuse.status_code == 403
    assert "set-cookie" not in reuse.headers


def test_pairing_rejects_missing_or_wrong_code(kiosk_client: TestClient) -> None:
    kiosk_client.post("/kiosk/pairing-code/rotate")
    assert kiosk_client.get("/kiosk/pair", follow_redirects=False).status_code == 403
    assert kiosk_client.get("/kiosk/pair?code=guess", follow_redirects=False).status_code == 403


def test_booth_mutation_requires_device_cookie(
    kiosk_client: TestClient, container: Container
) -> None:
    assert kiosk_client.post("/api/booth/ping").status_code == 401
    assert kiosk_client.get("/api/kiosk/status").json() == {"paired": False}

    code = _rotate_and_read(kiosk_client, container)
    kiosk_client.get(f"/kiosk/pair?code={code}", follow_redirects=False)
    assert kiosk_client.post("/api/booth/ping").json() == {"ok": True}
    assert kiosk_client.get("/api/kiosk/status").json() == {"paired": True}


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
