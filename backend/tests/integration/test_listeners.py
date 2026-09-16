"""Listener separation: kiosk = loopback + Host allowlist; delivery = delivery routes only."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.core.errors import InstanceGuardError
from photobooth.core.listeners import build_server, listener_specs, serve_together
from photobooth.main import KioskAppOptions, create_delivery_app, create_kiosk_app
from tests.conftest import make_settings


@pytest.mark.parametrize(
    "host",
    ["evil.example", "127.0.0.1.nip.io", "192.168.1.20", "photobooth.local", ""],
)
def test_kiosk_rejects_non_allowlisted_host(kiosk_client: TestClient, host: str) -> None:
    response = kiosk_client.get("/api/health", headers={"Host": host})
    assert response.status_code == 400


@pytest.mark.parametrize("host", ["localhost:8111", "127.0.0.1:5191", "LOCALHOST", "127.0.0.1"])
def test_kiosk_accepts_allowlisted_host(kiosk_client: TestClient, host: str) -> None:
    assert kiosk_client.get("/api/health", headers={"Host": host}).status_code == 200


def test_kiosk_rejects_oversized_body(container: Container) -> None:
    app = create_kiosk_app(container.registry, KioskAppOptions(max_request_bytes=1024))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post("/kiosk/pairing-code/rotate", content=b"x" * 2048)
    assert response.status_code == 413


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/health"),
        ("GET", "/api/version"),
        ("GET", "/api/admin/anything"),
        ("POST", "/api/booth/ping"),
        ("GET", "/kiosk/pair?code=x"),
        ("POST", "/kiosk/pairing-code/rotate"),
        ("GET", "/api/openapi.json"),
        ("GET", "/docs"),
        ("POST", "/d/_alive"),
        ("GET", "/"),
    ],
)
def test_delivery_listener_exposes_only_delivery_routes(
    delivery_client: TestClient, method: str, path: str
) -> None:
    response = delivery_client.request(method, path)
    assert response.status_code == 404
    assert response.text == "not found"


def test_delivery_alive(delivery_client: TestClient) -> None:
    response = delivery_client.get("/d/_alive")
    assert response.status_code == 200
    assert response.text == "ok"


def test_listener_specs_refuse_non_loopback_kiosk(thai_root: Path) -> None:
    settings = make_settings(thai_root, kiosk_host="0.0.0.0")
    with pytest.raises(InstanceGuardError):
        listener_specs(settings)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _lan_ipv4() -> str | None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1; no packet is sent for UDP connect
            address = str(sock.getsockname()[0])
        except OSError:
            return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address


@contextlib.contextmanager
def _running(servers: list[uvicorn.Server]) -> Iterator[None]:
    loop = asyncio.new_event_loop()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            loop.run_until_complete(serve_together(servers))
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    for server in servers:
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not all(s.started for s in servers):
        if errors or time.monotonic() > deadline:
            raise RuntimeError(f"servers did not start: {errors}")
        time.sleep(0.05)
    try:
        yield
    finally:
        for server in servers:
            server.should_exit = True
        thread.join(timeout=20)
        loop.close()


def test_real_sockets_kiosk_bound_to_loopback_only(container: Container) -> None:
    kiosk_port, delivery_port = _free_port(), _free_port()
    settings = make_settings(
        container.settings.instance_root, kiosk_port=kiosk_port, delivery_port=delivery_port
    )
    kiosk_spec, delivery_spec = listener_specs(settings)
    kiosk = build_server(create_kiosk_app(container.registry, KioskAppOptions()), kiosk_spec)
    delivery = build_server(create_delivery_app(), delivery_spec)

    with _running([kiosk, delivery]):
        bound = [sock.getsockname() for srv in kiosk.servers for sock in srv.sockets]
        assert bound and all(addr[0] == "127.0.0.1" for addr in bound)
        assert all(addr[1] == kiosk_port for addr in bound)

        ok = httpx.get(f"http://127.0.0.1:{kiosk_port}/api/health", timeout=5)
        assert ok.status_code == 200
        alive = httpx.get(f"http://127.0.0.1:{delivery_port}/d/_alive", timeout=5)
        assert alive.text == "ok"
        leaked = httpx.get(f"http://127.0.0.1:{delivery_port}/api/health", timeout=5)
        assert leaked.status_code == 404

        lan = _lan_ipv4()
        if lan is not None:
            with pytest.raises(httpx.ConnectError):
                httpx.get(f"http://{lan}:{kiosk_port}/api/health", timeout=3)
