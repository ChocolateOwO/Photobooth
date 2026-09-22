"""Participant frame choice: only the active event's frames, in order, with their session plan."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

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
    client: TestClient, headers: dict[str, str], frames: list[str], surprise: bool = False
) -> dict[str, Any]:
    profile = client.post(
        PROFILES,
        json={
            "name": "Party",
            "title": "Hi",
            "available_frames": frames,
            "allow_surprise_me": surprise,
        },
        headers=headers,
    ).json()
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
