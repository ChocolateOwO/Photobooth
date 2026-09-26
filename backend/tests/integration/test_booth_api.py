"""Participant frame choice: only the active event's frames, in order, with their session plan."""

from __future__ import annotations

import io
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from photobooth.container import Container
from photobooth.modules.frames.builtin import builtin_frame_id
from tests.integration.admin_support import ORIGIN, device_headers, login
from tests.integration.test_frames_api import upload

MENU = "/api/booth/frames"
SESSIONS = "/api/booth/sessions"
START = {"idempotency_key": "booth-api-start-1"}
PROFILES = "/api/admin/profiles"
STRIP = builtin_frame_id("midnight", "strip_2x6")
GOLD34 = builtin_frame_id("celebration_gold", "print_3x4")
LIGHT46 = builtin_frame_id("minimal_light", "print_4x6")


def _activate(
    client: TestClient,
    headers: dict[str, str],
    layouts: list[str],
    surprise: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    response = client.post(
        PROFILES,
        json={
            "name": "Party",
            "title": "Hi",
            "enabled_layouts": layouts,
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
    _s, other = upload(kiosk_client, headers, key="print_4x6", name="Not offered")
    profile = _activate(kiosk_client, headers, ["strip_2x6", "print_3x4"], surprise=True)

    # Participants do not need an admin session: a paired kiosk browser is enough.
    kiosk_client.cookies.delete("pb_admin_dummy", path="/api/admin")
    menu = kiosk_client.get(MENU)
    assert menu.status_code == 200, menu.text
    assert menu.headers["cache-control"] == "no-store"
    data = menu.json()
    # Every valid frame of the chosen sizes (also uploads), sizes in catalogue order, built-in
    # frames first; nothing of a size the event does not offer.
    assert [f["id"] for f in data["frames"]] == [
        GOLD34,
        builtin_frame_id("midnight", "print_3x4"),
        builtin_frame_id("minimal_light", "print_3x4"),
        builtin_frame_id("celebration_gold", "strip_2x6"),
        STRIP,
        builtin_frame_id("minimal_light", "strip_2x6"),
        mine["id"],
    ]
    assert other["id"] not in [f["id"] for f in data["frames"]]
    assert data["layouts"] == ["print_3x4", "strip_2x6"]
    assert data["countdown_seconds"] == 5
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
    assert "print_4x6" not in plans

    # Nothing about files, storage or where a frame came from reaches participants.
    for frame in data["frames"]:
        assert set(frame) == {"id", "name", "preview_url", "plan"}
        assert frame["preview_url"].startswith(f"/api/booth/frames/{frame['id']}/preview.jpg?v=")
    text = menu.text.lower()
    for secret in ("builtin", "built-in", "uploaded", "sha256", "storage", "media_asset", "family"):
        assert secret not in text


def test_previews_only_for_offered_frames(kiosk_client: TestClient, container: Container) -> None:
    headers = login(kiosk_client, container)
    _activate(kiosk_client, headers, ["print_3x4"])
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
    _activate(kiosk_client, headers, ["strip_2x6"], surprise=True)
    several = kiosk_client.get(MENU).json()
    assert len(several["frames"]) == 3 and several["allow_surprise_me"] is True


def test_the_menu_carries_the_plan_of_every_offered_frame(
    kiosk_client: TestClient, container: Container
) -> None:
    """Confirming a frame is part of a visit now; the menu still says what each frame means."""
    headers = login(kiosk_client, container)
    _activate(kiosk_client, headers, ["strip_2x6", "print_4x6"])
    device = _device_only(headers)
    menu = kiosk_client.get(MENU, headers=device).json()
    plan = next(frame["plan"] for frame in menu["frames"] if frame["id"] == LIGHT46)
    assert plan == {
        "frame_id": LIGHT46,
        "template_key": "print_4x6",
        "layout_label": "4×6",
        "captures": 4,
        "outputs": 1,
        "photos_per_output": 4,
        "output_capture_groups": [[1, 2, 3, 4]],
        "output_label": None,
    }
    assert GOLD34 not in [frame["id"] for frame in menu["frames"]]  # its size is not offered


def test_booth_routes_need_the_paired_device(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _activate(kiosk_client, headers, ["strip_2x6"])
    key = headers["X-Photobooth-Device-Key"]
    no_key = {"Origin": ORIGIN}
    assert kiosk_client.post(SESSIONS, json=START, headers=no_key).status_code == 403
    assert (
        kiosk_client.post(
            SESSIONS,
            json=START,
            headers={**device_headers(key), "Origin": "http://evil"},
        ).status_code
        == 403
    )
    kiosk_client.cookies.clear()
    assert kiosk_client.get(MENU).status_code == 401
    assert kiosk_client.get(f"{MENU}/{STRIP}/preview.jpg").status_code == 401
    assert kiosk_client.post(SESSIONS, json=START, headers=device_headers(key)).status_code == 401


START = "/api/booth/start"


def _image(fmt: str, size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


def _pixels(data: bytes) -> list[Any]:
    with Image.open(io.BytesIO(data)) as image:
        return list(image.convert("RGBA").getdata())


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
        ["strip_2x6"],
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
    assert set(menu.json()) == {
        "frames",
        "layouts",
        "allow_surprise_me",
        "theme",
        "start_screen",
        "countdown_seconds",
    }
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
    assert got_logo.status_code == 200 and _pixels(got_logo.content) == _pixels(logo)
    assert got_logo.headers["content-type"] == "image/png"
    assert got_logo.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in got_logo.headers["content-security-policy"]
    got_background = kiosk_client.get(screen["background_url"])
    assert got_background.status_code == 200
    assert Image.open(io.BytesIO(got_background.content)).size == (640, 360)
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
    _activate(kiosk_client, headers, ["strip_2x6"], background_asset_id=background_id)
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
    _activate(kiosk_client, headers, ["strip_2x6"], logo_asset_id=logo_id)
    assert kiosk_client.get(f"{START}/logo").status_code == 200
    kiosk_client.cookies.clear()
    assert kiosk_client.get(f"{START}/logo").status_code == 401
    assert kiosk_client.get(MENU).status_code == 401


def test_start_images_carry_no_private_metadata(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    # A phone photo as background: EXIF with GPS, author and a rotated orientation.
    photo = Image.new("RGB", (400, 200), (120, 30, 30))
    exif = Image.Exif()
    exif[0x013B] = "Secret Photographer"  # Artist
    exif[0x0112] = 6  # Orientation: rotate 90 degrees clockwise to show upright
    exif[0x8825] = {1: "N", 2: (13.0, 45.0, 1.0)}  # GPS latitude
    buffer = io.BytesIO()
    photo.save(buffer, "JPEG", exif=exif, comment=b"Secret comment")
    background = buffer.getvalue()
    # A transparent logo with private PNG text chunks.
    info = PngInfo()
    info.add_text("Author", "Secret Designer")
    info.add_itxt("Comment", "Secret note")
    logo_image = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    logo_image.paste((250, 200, 0, 255), (10, 10, 60, 50))
    buffer = io.BytesIO()
    logo_image.save(buffer, "PNG", pnginfo=info)
    logo = buffer.getvalue()
    assert b"Secret" in background and b"Secret" in logo  # the uploads do carry it

    logo_id = _asset(kiosk_client, headers, "logo", logo, "image/png")
    background_id = _asset(kiosk_client, headers, "background", background, "image/jpeg")
    _activate(
        kiosk_client,
        headers,
        ["strip_2x6"],
        logo_asset_id=logo_id,
        background_asset_id=background_id,
    )

    served_background = kiosk_client.get(f"{START}/background")
    assert served_background.status_code == 200
    assert b"Secret" not in served_background.content
    with Image.open(io.BytesIO(served_background.content)) as image:
        assert image.format == "JPEG"
        assert image.size == (200, 400)  # turned upright, as a viewer would show it
        assert len(image.getexif()) == 0
        assert "comment" not in image.info

    served_logo = kiosk_client.get(f"{START}/logo")
    assert served_logo.status_code == 200 and served_logo.headers["content-type"] == "image/png"
    assert b"Secret" not in served_logo.content
    with Image.open(io.BytesIO(served_logo.content)) as image:
        assert image.mode == "RGBA"  # transparency kept
        assert not getattr(image, "text", {})
        assert image.getpixel((0, 0))[3] == 0 and image.getpixel((20, 20)) == (250, 200, 0, 255)
