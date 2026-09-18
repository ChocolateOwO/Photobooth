"""Theme API: catalogue, offline extraction from uploaded backgrounds, authorization."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from photobooth.container import Container
from photobooth.modules.themes.domain import TOKEN_KEYS, contrast_problems, is_dark
from tests.integration.admin_support import CSRF_HEADER, login, png

BASE = "/api/admin/themes"


def _upload_background(client: TestClient, headers: dict[str, str], data: bytes) -> str:
    response = client.post(
        "/api/admin/assets",
        data={"kind": "background"},
        files={"file": ("bg.jpg", data, "image/jpeg")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _jpeg(page: tuple[int, int, int], spot: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (640, 400), page)
    ImageDraw.Draw(image).ellipse((220, 100, 420, 300), fill=spot)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=92)
    return buffer.getvalue()


def test_catalogue_lists_every_token_rule_and_complete_preset(
    kiosk_client: TestClient, container: Container
) -> None:
    login(kiosk_client, container)
    catalogue = kiosk_client.get(BASE).json()
    assert [t["key"] for t in catalogue["tokens"]] == list(TOKEN_KEYS)
    assert all(t["label"] and t["description"] and t["group"] for t in catalogue["tokens"])
    assert len(catalogue["presets"]) >= 6
    for preset in catalogue["presets"]:
        assert set(preset["tokens"]) == set(TOKEN_KEYS)
        assert contrast_problems(preset["tokens"]) == []
    assert catalogue["default_preset"] in {p["id"] for p in catalogue["presets"]}
    assert {r["minimum"] for r in catalogue["contrast_rules"]} == {3.0, 4.5}


@pytest.mark.parametrize(
    ("page", "spot", "dark"),
    [
        ((245, 238, 225), (190, 40, 80), False),  # light
        ((12, 18, 44), (40, 190, 170), True),  # dark
        ((120, 120, 120), (135, 135, 135), None),  # monochrome, low contrast
    ],
)
def test_extract_builds_an_accessible_theme_from_the_background(
    kiosk_client: TestClient,
    container: Container,
    page: tuple[int, int, int],
    spot: tuple[int, int, int],
    dark: bool | None,
) -> None:
    headers = login(kiosk_client, container)
    data = _jpeg(page, spot)
    asset_id = _upload_background(kiosk_client, headers, data)
    stored_before = kiosk_client.get(f"/api/admin/assets/{asset_id}/content").content

    response = kiosk_client.post(
        f"{BASE}/extract", json={"background_asset_id": asset_id}, headers=headers
    )
    assert response.status_code == 200, response.text
    theme = response.json()
    assert theme["message"] == "Colors extracted from background"
    assert theme["source"] == "extracted" and theme["preset"] is None
    assert 1 <= len(theme["palette"]) <= 8
    assert set(theme["tokens"]) == set(TOKEN_KEYS)
    assert contrast_problems(theme["tokens"]) == []
    if dark is not None:
        assert is_dark(theme["tokens"]) is dark
    # The uploaded file is never modified by extraction.
    assert kiosk_client.get(f"/api/admin/assets/{asset_id}/content").content == stored_before
    # Nothing was saved anywhere: extraction only proposes a theme.
    assert kiosk_client.get("/api/admin/profiles").json() == []


def test_a_new_background_gives_a_new_palette(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    first = _upload_background(kiosk_client, headers, _jpeg((245, 238, 225), (190, 40, 80)))
    second = _upload_background(kiosk_client, headers, _jpeg((12, 18, 44), (40, 190, 170)))
    a = kiosk_client.post(f"{BASE}/extract", json={"background_asset_id": first}, headers=headers)
    b = kiosk_client.post(f"{BASE}/extract", json={"background_asset_id": second}, headers=headers)
    assert a.json()["palette"] != b.json()["palette"]
    assert a.json()["tokens"]["background"] != b.json()["tokens"]["background"]


def test_extract_refuses_unknown_assets_and_logos(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    missing = kiosk_client.post(
        f"{BASE}/extract",
        json={"background_asset_id": "00000000-0000-4000-8000-000000000000"},
        headers=headers,
    )
    assert missing.status_code == 422 and "Upload it again" in missing.json()["detail"]
    logo = kiosk_client.post(
        "/api/admin/assets",
        data={"kind": "logo"},
        files={"file": ("l.png", png(), "image/png")},
        headers=headers,
    ).json()["id"]
    refused = kiosk_client.post(
        f"{BASE}/extract", json={"background_asset_id": logo}, headers=headers
    )
    assert refused.status_code == 422
    bad = kiosk_client.post(
        f"{BASE}/extract", json={"background_asset_id": "../x"}, headers=headers
    )
    assert bad.status_code == 422


def test_themes_require_a_paired_device_an_admin_and_csrf(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    asset_id = _upload_background(kiosk_client, headers, _jpeg((10, 10, 10), (200, 0, 0)))
    no_csrf = {k: v for k, v in headers.items() if k != CSRF_HEADER}
    assert (
        kiosk_client.post(
            f"{BASE}/extract", json={"background_asset_id": asset_id}, headers=no_csrf
        ).status_code
        == 403
    )
    kiosk_client.cookies.delete("pb_admin_dummy", path="/api/admin")
    assert kiosk_client.get(BASE).status_code == 401
    assert (
        kiosk_client.post(
            f"{BASE}/extract", json={"background_asset_id": asset_id}, headers=headers
        ).status_code
        == 401
    )
