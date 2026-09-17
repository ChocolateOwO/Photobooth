"""Logo/background uploads: validation, content-addressed storage, no client paths."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from photobooth.container import Container
from tests.integration.admin_support import jpeg, login, png


def _upload(
    client: TestClient,
    headers: dict[str, str],
    kind: str,
    data: bytes,
    filename: str = "logo.png",
    content_type: str = "image/png",
) -> tuple[int, dict[str, object]]:
    response = client.post(
        "/api/admin/assets",
        data={"kind": kind},
        files={"file": (filename, data, content_type)},
        headers=headers,
    )
    return response.status_code, response.json()


def test_upload_logo_and_background_then_read_back(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    status, logo = _upload(kiosk_client, headers, "logo", png((128, 64)))
    assert status == 201, logo
    assert logo["kind"] == "logo" and logo["mime"] == "image/png"
    assert (logo["width"], logo["height"]) == (128, 64)
    assert "storage_key" not in logo

    status, background = _upload(
        kiosk_client, headers, "background", jpeg(), "bg.jpg", "image/jpeg"
    )
    assert status == 201 and background["mime"] == "image/jpeg"

    meta = kiosk_client.get(f"/api/admin/assets/{logo['id']}")
    assert meta.status_code == 200 and meta.json() == logo
    content = kiosk_client.get(f"/api/admin/assets/{logo['id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.content == png((128, 64))


def test_duplicate_upload_returns_the_same_asset(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    _, first = _upload(kiosk_client, headers, "logo", png())
    status, second = _upload(kiosk_client, headers, "logo", png(), "other-name.png")
    assert status == 201 and second["id"] == first["id"]
    files = [p for p in container.settings.storage_dir.rglob("*") if p.is_file()]
    assert len(files) == 1


def test_client_filename_and_paths_are_ignored(
    kiosk_client: TestClient, container: Container, thai_root: Path
) -> None:
    headers = login(kiosk_client, container)
    for name in (
        "../../escape.png",
        "..\\..\\escape.png",
        "C:\\Windows\\escape.png",
        "/etc/escape.png",
        "assets/../../../escape.png",
    ):
        status, body = _upload(
            kiosk_client, headers, "logo", png(color=(len(name), 0, 0, 255)), name
        )
        assert status == 201, body
    storage = container.settings.storage_dir.resolve()
    for path in thai_root.rglob("*.png"):
        assert storage in path.resolve().parents, path
    assert not list(thai_root.rglob("escape*"))


def test_invalid_uploads_are_refused_and_nothing_is_stored(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    cases: list[tuple[str, bytes, str]] = [
        ("logo", b"", "image/png"),
        ("logo", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        ("logo", b"GIF89a" + b"\x00" * 64, "image/gif"),
        ("logo", png()[:40], "image/png"),
        ("logo", png((5000, 20)), "image/png"),
        ("background", b"MZ\x90\x00 fake exe", "image/jpeg"),
    ]
    for kind, data, content_type in cases:
        status, body = _upload(kiosk_client, headers, kind, data, "x.png", content_type)
        assert status == 422, (kind, content_type, body)
    assert _upload(kiosk_client, headers, "frame", png())[0] == 422  # frames are Phase 5
    assert _upload(kiosk_client, headers, "../logo", png())[0] == 422
    assert not [p for p in container.settings.storage_dir.rglob("*") if p.is_file()]


def test_oversized_upload_is_refused_with_413(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    too_big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1)
    status, _ = _upload(kiosk_client, headers, "logo", too_big)
    assert status == 413


def test_assets_require_admin(kiosk_client: TestClient, container: Container) -> None:
    headers = login(kiosk_client, container)
    _, logo = _upload(kiosk_client, headers, "logo", png())
    kiosk_client.cookies.delete("pb_admin_dummy", path="/api/admin")
    assert kiosk_client.get(f"/api/admin/assets/{logo['id']}").status_code == 401
    assert kiosk_client.get(f"/api/admin/assets/{logo['id']}/content").status_code == 401
    assert _upload(kiosk_client, headers, "logo", png((32, 32)))[0] == 401


def test_unknown_or_malformed_asset_ids(kiosk_client: TestClient, container: Container) -> None:
    login(kiosk_client, container)
    missing = "00000000-0000-4000-8000-000000000000"
    assert kiosk_client.get(f"/api/admin/assets/{missing}").status_code == 404
    assert kiosk_client.get(f"/api/admin/assets/{missing}/content").status_code == 404
    for bad in ("..%2F..%2Fphotobooth.sqlite", "not-a-uuid", "%2e%2e"):
        assert kiosk_client.get(f"/api/admin/assets/{bad}").status_code in (404, 422), bad
