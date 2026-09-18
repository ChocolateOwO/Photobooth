"""Frame manager API: upload, validate, preview, replace, rename, delete, authorization."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.migrations import Migrator
from photobooth.main import KioskAppOptions, create_kiosk_app
from photobooth.modules.templates.repository import JsonTemplateRepository
from tests.integration.admin_support import login
from tests.unit.test_frame_validator import frame_png

TEMPLATES = {t.key: t for t in JsonTemplateRepository().latest()}
BASE = "/api/admin/frames"


def upload(
    client: TestClient,
    headers: dict[str, str],
    key: str = "strip_2x6",
    name: str = "Blue border",
    data: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
    payload = data if data is not None else frame_png(TEMPLATES[key]) if key in TEMPLATES else b""
    response = client.post(
        BASE,
        data={"template_key": key, "name": name},
        files={"file": ("anything.png", payload, "image/png")},
        headers=headers,
    )
    body: dict[str, Any] = {} if response.status_code == 204 else response.json()
    return response.status_code, body


def test_upload_lists_and_serves_the_original_bytes(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    original = frame_png(TEMPLATES["strip_2x6"])
    status, frame = upload(kiosk_client, headers, data=original)
    assert status == 201, frame
    assert frame["template_key"] == "strip_2x6"
    assert frame["template_version"] == TEMPLATES["strip_2x6"].version
    assert (frame["width"], frame["height"]) == (600, 1800)
    assert frame["name"] == "Blue border" and frame["status"] == "valid"
    assert frame["warnings"] == [] and frame["slot_transparency"] == [1.0, 1.0, 1.0]

    listed = kiosk_client.get(BASE).json()
    assert [f["id"] for f in listed] == [frame["id"]]
    assert kiosk_client.get(f"{BASE}?template_key=print_3x4").json() == []

    content = kiosk_client.get(f"{BASE}/{frame['id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.content == original  # never modified


@pytest.mark.parametrize("key", ["strip_2x6", "print_3x4", "print_4x6"])
def test_every_approved_layout_accepts_its_own_frame_and_previews_it(
    kiosk_client: TestClient, container: Container, key: str
) -> None:
    headers = login(kiosk_client, container)
    status, frame = upload(kiosk_client, headers, key=key, name=f"{key} frame")
    assert status == 201, frame
    template = TEMPLATES[key]
    for output_index in range(1, template.outputs_per_session + 1):
        preview = kiosk_client.get(f"{BASE}/{frame['id']}/preview/{output_index}.jpg")
        assert preview.status_code == 200, preview.text
        assert preview.headers["content-type"] == "image/jpeg"
        assert preview.content.startswith(b"\xff\xd8")
    missing = kiosk_client.get(f"{BASE}/{frame['id']}/preview/9.jpg")
    assert missing.status_code == 422


def test_wrong_layout_size_and_opaque_slots_are_refused(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    # A valid 2x6 frame is the wrong size for 3x4.
    status, body = upload(
        kiosk_client, headers, key="print_3x4", data=frame_png(TEMPLATES["strip_2x6"])
    )
    assert status == 422 and "exactly 900 x 1200 px" in body["detail"]

    status, body = upload(
        kiosk_client, headers, data=frame_png(TEMPLATES["strip_2x6"], clear_slots=False)
    )
    assert status == 422 and "Photo 1 area must be at least 95% transparent" in body["detail"]

    status, body = upload(kiosk_client, headers, data=b"<svg/>")
    assert status == 422 and "valid PNG" in body["detail"]

    status, body = upload(
        kiosk_client, headers, key="no_such_layout", data=frame_png(TEMPLATES["strip_2x6"])
    )
    assert status == 422 and "Unknown photo layout" in body["detail"]

    for bad_name in ("", "   ", "x" * 81, "bad\u0000name"):
        status, body = upload(kiosk_client, headers, name=bad_name)
        assert status == 422, (bad_name, body)
    assert kiosk_client.get(BASE).json() == []


def test_client_file_names_and_paths_are_ignored(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    names = ("../../escape.png", "C:\\Windows\\x.png", "..\\..\\x.png")
    for index, filename in enumerate(names):
        response = kiosk_client.post(
            BASE,
            data={"template_key": "strip_2x6", "name": f"Frame {index}"},
            files={
                "file": (
                    filename,
                    frame_png(TEMPLATES["strip_2x6"], fill=(index, 10, 10, 255)),
                    "image/png",
                )
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        # The client file name is never stored or echoed back.
        assert "escape" not in str(response.json()) and "Windows" not in str(response.json())
    storage = container.settings.storage_dir.resolve()
    files = [p for p in storage.rglob("*") if p.is_file()]
    assert files and all(storage in p.resolve().parents for p in files)
    assert not list(container.settings.instance_root.glob("escape*"))


def test_duplicate_name_per_layout_is_refused_but_allowed_for_another_layout(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    assert upload(kiosk_client, headers, name="Gold")[0] == 201
    status, body = upload(kiosk_client, headers, name="Gold")
    assert status == 422 and "already exists" in body["detail"]
    assert upload(kiosk_client, headers, key="print_4x6", name="Gold")[0] == 201


def test_replace_and_rename_keep_the_frame_id(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _status, frame = upload(kiosk_client, headers)
    replacement = frame_png(TEMPLATES["strip_2x6"], fill=(200, 10, 10, 255))
    assert replacement != frame_png(TEMPLATES["strip_2x6"])

    bad = kiosk_client.post(
        f"{BASE}/{frame['id']}/replace",
        files={"file": ("f.png", frame_png(TEMPLATES["print_4x6"]), "image/png")},
        headers=headers,
    )
    assert bad.status_code == 422 and "exactly 600 x 1800 px" in bad.json()["detail"]

    good = kiosk_client.post(
        f"{BASE}/{frame['id']}/replace",
        files={"file": ("f.png", replacement, "image/png")},
        headers=headers,
    )
    assert good.status_code == 200
    assert good.json()["id"] == frame["id"]
    assert kiosk_client.get(f"{BASE}/{frame['id']}/content").content == replacement

    renamed = kiosk_client.put(
        f"{BASE}/{frame['id']}/name", json={"name": "  Renamed  frame "}, headers=headers
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed frame"
    assert (
        kiosk_client.put(
            f"{BASE}/{frame['id']}/name", json={"name": ""}, headers=headers
        ).status_code
        == 422
    )


def _frame_files(container: Container) -> list[str]:
    root = container.settings.storage_dir / "assets" / "frame"
    return sorted(p.name for p in root.rglob("*") if p.is_file()) if root.exists() else []


def test_stored_frame_files_are_removed_when_nothing_uses_them(
    kiosk_client: TestClient, container: Container
) -> None:
    """P5-003: delete, replace and refused uploads leave no orphan files or media rows."""
    headers = login(kiosk_client, container)
    shared_bytes = frame_png(TEMPLATES["strip_2x6"])
    _status, first = upload(kiosk_client, headers, name="First", data=shared_bytes)
    _status, twin = upload(kiosk_client, headers, name="Twin", data=shared_bytes)
    frames = container.frame_service
    first_asset = frames.get(first["id"]).media_asset_id
    assert first_asset == frames.get(twin["id"]).media_asset_id  # content-addressed, one file
    assert len(_frame_files(container)) == 1

    # A refused duplicate name with new bytes stores nothing.
    other = frame_png(TEMPLATES["strip_2x6"], fill=(1, 2, 3, 255))
    status, _body = upload(kiosk_client, headers, name="First", data=other)
    assert status == 422
    assert len(_frame_files(container)) == 1

    # Deleting one of two frames sharing a file keeps the file for the other.
    assert kiosk_client.delete(f"{BASE}/{twin['id']}", headers=headers).status_code == 204
    assert len(_frame_files(container)) == 1
    assert kiosk_client.get(f"{BASE}/{first['id']}/content").content == shared_bytes

    # Replacing the file removes the previous one.
    replaced = kiosk_client.post(
        f"{BASE}/{first['id']}/replace",
        files={"file": ("f.png", other, "image/png")},
        headers=headers,
    )
    assert replaced.status_code == 200
    assert len(_frame_files(container)) == 1
    assert container.asset_service.exists(first_asset, "frame") is False

    # Deleting the last frame removes its file and media row.
    new_asset = frames.get(first["id"]).media_asset_id
    assert kiosk_client.delete(f"{BASE}/{first['id']}", headers=headers).status_code == 204
    assert _frame_files(container) == []
    assert container.asset_service.exists(new_asset, "frame") is False


def test_frames_require_a_paired_device_and_an_admin_session(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _status, frame = upload(kiosk_client, headers)
    without_csrf = {k: v for k, v in headers.items() if k != "X-Photobooth-Admin-CSRF"}
    assert kiosk_client.delete(f"{BASE}/{frame['id']}", headers=without_csrf).status_code == 403

    kiosk_client.cookies.delete("pb_admin_dummy", path="/api/admin")
    assert kiosk_client.get(BASE).status_code == 401
    assert kiosk_client.get(f"{BASE}/{frame['id']}").status_code == 401
    assert kiosk_client.get(f"{BASE}/{frame['id']}/content").status_code == 401
    assert kiosk_client.get(f"{BASE}/{frame['id']}/preview/1.jpg").status_code == 401
    assert upload(kiosk_client, headers, name="Sneaky")[0] == 401
    assert kiosk_client.delete(f"{BASE}/{frame['id']}", headers=headers).status_code == 401


def test_unknown_and_malformed_frame_ids(kiosk_client: TestClient, container: Container) -> None:
    login(kiosk_client, container)
    missing = "00000000-0000-4000-8000-000000000000"
    assert kiosk_client.get(f"{BASE}/{missing}").status_code == 404
    assert kiosk_client.get(f"{BASE}/{missing}/content").status_code == 404
    assert kiosk_client.get(f"{BASE}/{missing}/preview/1.jpg").status_code == 404
    assert kiosk_client.get(f"{BASE}/not-a-uuid").status_code == 422


def test_frames_survive_a_restart(settings: AppSettings) -> None:
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    try:
        app = create_kiosk_app(first.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            headers = login(client, first)
            _status, frame = upload(client, headers, name="Survivor")
            original = client.get(f"{BASE}/{frame['id']}/content").content
    finally:
        first.close()

    second = Container(settings)
    try:
        app = create_kiosk_app(second.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            login(client, second, create_user=False)
            reloaded = client.get(f"{BASE}/{frame['id']}").json()
            assert reloaded["name"] == "Survivor"
            assert reloaded["slot_transparency"] == [1.0, 1.0, 1.0]
            assert client.get(f"{BASE}/{frame['id']}/content").content == original
            assert client.get(f"{BASE}/{frame['id']}/preview/1.jpg").status_code == 200
    finally:
        second.close()
