"""TV screen: the booth on a TV's browser over the LAN, photographing with the PC's camera."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.core.screen_gate import ScreenGateMiddleware, is_blocked_path
from photobooth.main import KioskAppOptions, create_kiosk_app
from photobooth.modules.screen.domain import CameraUnavailableError, PcCameraInfo
from photobooth.modules.screen.opencv import JsonCameraChoiceStore
from photobooth.modules.screen.service import PcCameraService, TvPairingService

from .admin_support import KEY_HEADER, adopt_device, login

TV = "http://192.168.1.50:18125"


class FakeCameras:
    def __init__(self) -> None:
        self.asked: list[tuple[int, int | None]] = []

    def available(self) -> list[PcCameraInfo]:
        return [PcCameraInfo(0, "Camera 1"), PcCameraInfo(1, "Camera 2")]

    def frame(self, index: int, max_width: int | None) -> bytes:
        self.asked.append((index, max_width))
        if index > 1:
            raise CameraUnavailableError("no such camera")
        return b"\xff\xd8jpeg-" + str(index).encode()

    def close(self) -> None:
        pass


@pytest.fixture
def cameras(container: Container) -> FakeCameras:
    fake = FakeCameras()
    store = JsonCameraChoiceStore(container.settings.config_dir / "pc-camera.json")
    container.registry.register(PcCameraService, PcCameraService(fake, store))
    return fake


@pytest.fixture
def tv_client(container: Container) -> Iterator[TestClient]:
    app = ScreenGateMiddleware(
        create_kiosk_app(container.registry, KioskAppOptions()), container.settings.kiosk_port
    )
    with TestClient(app, base_url=TV) as client:
        yield client


def _pair_tv(tv_client: TestClient, container: Container) -> str:
    code, _ttl = container.registry.get(TvPairingService).new_code()
    response = tv_client.get(f"/tv/pair?code={code}", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/booth#pair-key=")
    return location.removeprefix("/booth#pair-key=")


@pytest.mark.parametrize(
    "path",
    [
        "/admin",
        "/admin/frames",
        "/api/admin/system",
        "/api/admin/screen",
        "/kiosk/pair",
        "/kiosk/pairing-code/rotate",
        "/api/openapi.json",
        "/ADMIN",
    ],
)
def test_the_tv_never_reaches_admin_or_the_launcher(path: str) -> None:
    assert is_blocked_path(path)


@pytest.mark.parametrize("path", ["/", "/booth", "/tv", "/api/booth/frames", "/api/kiosk/status"])
def test_the_tv_reaches_the_booth(path: str) -> None:
    assert not is_blocked_path(path)


def test_blocked_paths_answer_404_even_for_a_logged_in_admin(
    tv_client: TestClient, kiosk_client: TestClient, container: Container
) -> None:
    login(kiosk_client, container)
    tv_client.cookies.update(kiosk_client.cookies)
    assert tv_client.get("/api/admin/system").status_code == 404
    assert tv_client.get("/api/admin/screen").status_code == 404


def test_a_host_name_is_refused_only_ip_addresses_count(container: Container) -> None:
    app = ScreenGateMiddleware(
        create_kiosk_app(container.registry, KioskAppOptions()), container.settings.kiosk_port
    )
    with TestClient(app, base_url="http://evil.example:18125") as client:
        assert client.get("/api/health").status_code == 400


def test_the_tv_pairs_with_the_short_code_and_can_then_act(
    tv_client: TestClient, container: Container
) -> None:
    key = _pair_tv(tv_client, container)
    # A mutation from the TV page's own origin is accepted as the kiosk's.
    ok = tv_client.post("/api/booth/ping", headers={"Origin": TV, KEY_HEADER: key})
    assert ok.status_code == 200, ok.text
    # Another site's origin is still refused.
    foreign = tv_client.post(
        "/api/booth/ping", headers={"Origin": "http://192.168.1.99:80", KEY_HEADER: key}
    )
    assert foreign.status_code == 403


def test_a_wrong_or_used_code_does_not_pair(tv_client: TestClient, container: Container) -> None:
    pairing = container.registry.get(TvPairingService)
    code, _ttl = pairing.new_code()
    wrong = "000000" if code != "000000" else "111111"
    assert tv_client.get(f"/tv/pair?code={wrong}", follow_redirects=False).status_code == 403
    assert tv_client.get(f"/tv/pair?code={code}", follow_redirects=False).status_code == 303
    assert tv_client.get(f"/tv/pair?code={code}", follow_redirects=False).status_code == 403


def test_five_wrong_tries_end_the_code(container: Container) -> None:
    pairing = TvPairingService(container.device_credentials)
    code, _ttl = pairing.new_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert pairing.consume(wrong) is None
    assert pairing.consume(code) is None


def test_a_code_expires(container: Container) -> None:
    now = [0.0]
    pairing = TvPairingService(container.device_credentials, clock=lambda: now[0])
    code, ttl = pairing.new_code()
    now[0] = ttl + 1
    assert pairing.consume(code) is None


def test_the_tv_page_asks_for_the_code(tv_client: TestClient) -> None:
    page = tv_client.get("/tv")
    assert page.status_code == 200
    assert 'action="/tv/pair"' in page.text


def test_the_paired_tv_gets_pictures_of_the_chosen_camera(
    tv_client: TestClient, kiosk_client: TestClient, container: Container, cameras: FakeCameras
) -> None:
    assert tv_client.get("/api/booth/camera/frame.jpg").status_code == 401
    _pair_tv(tv_client, container)
    first = tv_client.get("/api/booth/camera/frame.jpg")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert first.content.endswith(b"-0")  # no choice yet: the first camera

    headers = login(kiosk_client, container)
    chosen = kiosk_client.put("/api/admin/screen/camera", json={"index": 1}, headers=headers)
    assert chosen.status_code == 200
    assert chosen.json()["camera_index"] == 1
    assert tv_client.get("/api/booth/camera/frame.jpg").content.endswith(b"-1")
    assert tv_client.get("/api/booth/camera/frame.jpg?preview=true").status_code == 200
    assert cameras.asked[-1] == (1, 1280)


def test_a_missing_camera_answers_503(
    kiosk_client: TestClient, container: Container, cameras: FakeCameras
) -> None:
    headers = login(kiosk_client, container)
    kiosk_client.put("/api/admin/screen/camera", json={"index": 5}, headers=headers)
    assert kiosk_client.get("/api/booth/camera/frame.jpg").status_code == 503
    assert kiosk_client.get("/api/admin/screen/cameras/5.jpg").status_code == 503


def test_admin_lists_cameras_and_shows_a_tv_code(
    kiosk_client: TestClient, container: Container, cameras: FakeCameras
) -> None:
    headers = login(kiosk_client, container)
    listed = kiosk_client.get("/api/admin/screen/cameras")
    assert listed.json() == [{"index": 0, "label": "Camera 1"}, {"index": 1, "label": "Camera 2"}]
    assert kiosk_client.get("/api/admin/screen/cameras/1.jpg").status_code == 200
    code = kiosk_client.post("/api/admin/screen/tv-code", headers=headers)
    assert code.status_code == 200
    assert len(code.json()["code"]) == 6
    assert code.json()["tv_url"] is None  # the test instance has no TV listener


def test_a_paired_device_without_admin_login_can_not_choose(
    kiosk_client: TestClient, container: Container, cameras: FakeCameras
) -> None:
    key = adopt_device(kiosk_client, container)
    response = kiosk_client.put(
        "/api/admin/screen/camera",
        json={"index": 1},
        headers={"Origin": "http://127.0.0.1:18111", KEY_HEADER: key},
    )
    assert response.status_code == 401
