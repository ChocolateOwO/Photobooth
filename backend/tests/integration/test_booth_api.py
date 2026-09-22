"""Participant frame choice: only the active event's frames, in order, with their session plan."""

from __future__ import annotations

import io
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from photobooth.container import Container
from photobooth.modules.frames.builtin import builtin_frame_id
from tests.integration.admin_support import ORIGIN, device_headers, login
from tests.integration.test_frames_api import upload

MENU = "/api/booth/frames"
CHOICE = "/api/booth/frame-choice"
PROFILES = "/api/admin/profiles"
STRIP = builtin_frame_id("midnight", "strip_2x6")
GOLD34 = builtin_frame_id("celebration_gold", "print_3x4")
LIGHT46 = builtin_frame_id("minimal_light", "print_4x6")


def _activate(
    client: TestClient,
    headers: dict[str, str],
    frames: list[str],
    surprise: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    response = client.post(
        PROFILES,
        json={
            "name": "Party",
            "title": "Hi",
            "available_frames": frames,
            "allow_surprise_me": surprise,
            **extra,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    profile = response.json()
    active = client.post(f"{PROFILES}/{profile['id']}/activate", headers=headers)
    assert active.status_code == 200, active.text
    result: dict[str, Any] = active.json()
    return result


def _device_only(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k != "X-Photobooth-Admin-CSRF"}


def test_no_active_event_means_no_menu(kiosk_client: TestClient, container: Container) -> None:
    login(kiosk_client, container)
    response = kiosk_client.get(MENU)
    assert response.status_code == 404 and "no event is active" in response.json()["detail"]


def test_menu_lists_only_offered_frames_in_order_with_their_plan(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _s, mine = upload(kiosk_client, headers, key="strip_2x6", name="Our strip")
    profile = _activate(kiosk_client, headers, [GOLD34, mine["id"], LIGHT46, STRIP], surprise=True)

    # Participants do not need an admin session: a paired kiosk browser is enough.
    kiosk_client.cookies.delete("pb_admin_dummy", path="/api/admin")
    menu = kiosk_client.get(MENU)
    assert menu.status_code == 200, menu.text
    assert menu.headers["cache-control"] == "no-store"
    data = menu.json()
    assert [f["id"] for f in data["frames"]] == [GOLD34, mine["id"], LIGHT46, STRIP]
    assert [f["name"] for f in data["frames"]] == [
        "Celebration Gold",
        "Our strip",
        "Minimal Light",
        "Midnight",
    ]
    assert data["layouts"] == ["print_3x4", "strip_2x6", "print_4x6"]
    assert data["allow_surprise_me"] is True
    assert data["theme"] == profile["settings"]["theme"]["tokens"]
    assert data["start_screen"] == {
        "start_button_text": "Start",
        "logo_url": None,
        "background_url": None,
    }

    plans = {f["plan"]["template_key"]: f["plan"] for f in data["frames"]}
    assert plans["strip_2x6"] | {"frame_id": None} == {
        "frame_id": None,
        "template_key": "strip_2x6",
        "layout_label": "2×6",
        "captures": 6,
        "outputs": 2,
        "photos_per_output": 3,
        "output_capture_groups": [[1, 2, 3], [4, 5, 6]],
        "output_label": "2 strips",
    }
    assert (plans["print_3x4"]["layout_label"], plans["print_3x4"]["captures"]) == ("3×4", 2)
    assert plans["print_3x4"]["output_label"] is None
    assert (plans["print_4x6"]["captures"], plans["print_4x6"]["outputs"]) == (4, 1)

    # Nothing about files, storage or where a frame came from reaches participants.
    for frame in data["frames"]:
        assert set(frame) == {"id", "name", "preview_url", "plan"}
        assert frame["preview_url"].startswith(f"/api/booth/frames/{frame['id']}/preview.jpg?v=")
    text = menu.text.lower()
    for secret in ("builtin", "built-in", "uploaded", "sha256", "storage", "media_asset", "family"):
        assert secret not in text


def test_previews_only_for_offered_frames(kiosk_client: TestClient, container: Container) -> None:
    headers = login(kiosk_client, container)
    _activate(kiosk_client, headers, [GOLD34])
    offered = kiosk_client.get(f"{MENU}/{GOLD34}/preview.jpg")
    assert offered.status_code == 200 and offered.content.startswith(b"\xff\xd8")
    assert offered.headers["content-type"] == "image/jpeg"
    not_offered = kiosk_client.get(f"{MENU}/{STRIP}/preview.jpg")
    assert not_offered.status_code == 404
    unknown = kiosk_client.get(f"{MENU}/00000000-0000-4000-8000-000000000000/preview.jpg")
    assert unknown.status_code == 404
    assert kiosk_client.get(f"{MENU}/not-an-id/preview.jpg").status_code == 422


def test_surprise_me_needs_two_frames(kiosk_client: TestClient, container: Container) -> None:
    headers = login(kiosk_client, container)
    _activate(kiosk_client, headers, [STRIP], surprise=True)
    single = kiosk_client.get(MENU).json()
    assert len(single["frames"]) == 1 and single["allow_surprise_me"] is False


def test_choosing_returns_the_plan_and_refuses_other_frames(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _activate(kiosk_client, headers, [STRIP, LIGHT46])
    device = _device_only(headers)
    chosen = kiosk_client.post(CHOICE, json={"frame_id": LIGHT46}, headers=device)
    assert chosen.status_code == 200, chosen.text
    assert chosen.json() == {
        "frame_id": LIGHT46,
        "template_key": "print_4x6",
        "layout_label": "4×6",
        "captures": 4,
        "outputs": 1,
        "photos_per_output": 4,
        "output_capture_groups": [[1, 2, 3, 4]],
        "output_label": None,
    }
    refused = kiosk_client.post(CHOICE, json={"frame_id": GOLD34}, headers=device)
    assert refused.status_code == 404
    assert kiosk_client.post(CHOICE, json={"frame_id": "x"}, headers=device).status_code == 422


def test_booth_routes_need_the_paired_device(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _activate(kiosk_client, headers, [STRIP])
    key = headers["X-Photobooth-Device-Key"]
    no_key = {"Origin": ORIGIN}
    assert kiosk_client.post(CHOICE, json={"frame_id": STRIP}, headers=no_key).status_code == 403
    assert (
        kiosk_client.post(
            CHOICE,
            json={"frame_id": STRIP},
            headers={**device_headers(key), "Origin": "http://evil"},
        ).status_code
        == 403
    )
    kiosk_client.cookies.clear()
    assert kiosk_client.get(MENU).status_code == 401
    assert kiosk_client.get(f"{MENU}/{STRIP}/preview.jpg").status_code == 401
    assert (
        kiosk_client.post(CHOICE, json={"frame_id": STRIP}, headers=device_headers(key)).status_code
        == 401
    )


START = "/api/booth/start"


def _image(fmt: str, size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


def _asset(client: TestClient, headers: dict[str, str], kind: str, data: bytes, mime: str) -> str:
    response = client.post(
        "/api/admin/assets",
        data={"kind": kind},
        files={"file": (f"{kind}.bin", data, mime)},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_start_screen_gives_only_presentation_data(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    logo = _image("PNG", (240, 120), (200, 40, 40))
    background = _image("JPEG", (640, 360), (20, 60, 120))
    logo_id = _asset(kiosk_client, headers, "logo", logo, "image/png")
    background_id = _asset(kiosk_client, headers, "background", background, "image/jpeg")
    _activate(
        kiosk_client,
        headers,
        [STRIP],
        name="Private profile name",
        title="Secret title text",
        subtitle="Secret subtitle text",
        start_button_text="Let's go",
        logo_asset_id=logo_id,
        background_asset_id=background_id,
    )
    kiosk_client.cookies.delete("pb_admin_dummy", path="/api/admin")

    menu = kiosk_client.get(MENU)
    assert menu.status_code == 200, menu.text
    screen = menu.json()["start_screen"]
    assert set(screen) == {"start_button_text", "logo_url", "background_url"}
    assert screen["start_button_text"] == "Let's go"
    assert screen["logo_url"].startswith(f"{START}/logo?v=")
    assert screen["background_url"].startswith(f"{START}/background?v=")
    assert set(menu.json()) == {"frames", "layouts", "allow_surprise_me", "theme", "start_screen"}
    # No asset ids, storage, profile internals or admin-only texts reach participants.
    text = menu.text
    for private in (
        logo_id,
        background_id,
        "Private profile name",
        "Secret title text",
        "Secret subtitle text",
        "revision",
        "is_active",
        "deleted_at",
        "asset_id",
        "storage",
        "sha256",
        "/api/admin",
    ):
        assert private not in text

    got_logo = kiosk_client.get(screen["logo_url"])
    assert got_logo.status_code == 200 and got_logo.content == logo
    assert got_logo.headers["content-type"] == "image/png"
    assert got_logo.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in got_logo.headers["content-security-policy"]
    got_background = kiosk_client.get(screen["background_url"])
    assert got_background.status_code == 200 and got_background.content == background
    assert got_background.headers["content-type"] == "image/jpeg"
    # Only the two named images of the active event: no other kind, no asset id.
    assert kiosk_client.get(f"{START}/frame").status_code == 422
    assert kiosk_client.get(f"{START}/{logo_id}").status_code == 422


def test_start_screen_without_images_or_with_a_lost_file_falls_back(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    assert kiosk_client.get(f"{START}/logo").status_code == 404  # no active event yet
    background_id = _asset(
        kiosk_client, headers, "background", _image("JPEG", (320, 200), (9, 9, 9)), "image/jpeg"
    )
    _activate(kiosk_client, headers, [STRIP], background_asset_id=background_id)
    screen = kiosk_client.get(MENU).json()["start_screen"]
    assert screen["logo_url"] is None and screen["start_button_text"] == "Start"
    assert kiosk_client.get(f"{START}/logo").status_code == 404

    # The stored file disappears (disk trouble): a plain 404, never a path or a server error.
    stored = container.asset_service.get(background_id).storage_key
    for path in container.settings.storage_dir.rglob("*"):
        if path.is_file() and path.as_posix().endswith(stored):
            path.unlink()
    lost = kiosk_client.get(f"{START}/background")
    assert lost.status_code == 404
    assert str(container.settings.storage_dir) not in lost.text and stored not in lost.text


def test_start_images_need_the_paired_device(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    logo_id = _asset(
        kiosk_client, headers, "logo", _image("PNG", (100, 50), (1, 2, 3)), "image/png"
    )
    _activate(kiosk_client, headers, [STRIP], logo_asset_id=logo_id)
    assert kiosk_client.get(f"{START}/logo").status_code == 200
    kiosk_client.cookies.clear()
    assert kiosk_client.get(f"{START}/logo").status_code == 401
    assert kiosk_client.get(MENU).status_code == 401
