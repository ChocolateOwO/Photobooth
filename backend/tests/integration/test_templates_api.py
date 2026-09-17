"""Specification API, blank PNG, guide PNG and sample render endpoints."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photobooth.modules.templates.imaging import SLOT_FILL


def test_list_returns_three_templates_with_links(kiosk_client: TestClient) -> None:
    response = kiosk_client.get("/api/templates")
    assert response.status_code == 200
    body = response.json()
    assert [t["key"] for t in body] == ["print_3x4", "print_4x6", "strip_2x6"]
    strip = body[2]
    assert strip["links"] == {
        "spec": "/api/templates/strip_2x6?version=1",
        "blank_png": "/api/templates/strip_2x6/blank.png?version=1",
        "guide_png": "/api/templates/strip_2x6/guide.png?version=1",
        "sample_jpgs": [
            "/api/render/samples/strip_2x6/1.jpg?version=1",
            "/api/render/samples/strip_2x6/2.jpg?version=1",
        ],
    }


def test_2x6_spec_contract(kiosk_client: TestClient) -> None:
    spec = kiosk_client.get("/api/templates/strip_2x6").json()
    assert spec["version"] == 1
    assert (spec["width_in"], spec["height_in"], spec["dpi"]) == (2, 6, 300)
    assert (spec["width_px"], spec["height_px"]) == (600, 1800)
    assert spec["captures_per_session"] == 6
    assert spec["outputs_per_session"] == 2
    assert spec["output_capture_groups"] == [[1, 2, 3], [4, 5, 6]]
    assert spec["slots"] == [
        {
            "index": 1,
            "x": 30,
            "y": 45,
            "w": 540,
            "h": 405,
            "fit": "cover",
            "anchor": "center",
            "aspect": "4:3",
        },
        {
            "index": 2,
            "x": 30,
            "y": 480,
            "w": 540,
            "h": 405,
            "fit": "cover",
            "anchor": "center",
            "aspect": "4:3",
        },
        {
            "index": 3,
            "x": 30,
            "y": 915,
            "w": 540,
            "h": 405,
            "fit": "cover",
            "anchor": "center",
            "aspect": "4:3",
        },
    ]
    assert spec["safe_area"] == {"x": 36, "y": 36, "w": 528, "h": 1728}
    assert spec["branding_area"] == {"x": 0, "y": 1350, "w": 600, "h": 450}
    assert spec["frame_rules"]["format"] == "PNG" and spec["frame_rules"]["mode"] == "RGBA"
    assert any(
        "exactly 600 x 1800 px (2 x 6 in at 300 DPI)" in line for line in spec["frame_requirements"]
    )


@pytest.mark.parametrize(
    ("key", "size", "slots"),
    [("print_3x4", (900, 1200), 2), ("print_4x6", (1200, 1800), 4)],
)
def test_other_specs(kiosk_client: TestClient, key: str, size: tuple[int, int], slots: int) -> None:
    spec = kiosk_client.get(f"/api/templates/{key}?version=1").json()
    assert (spec["width_px"], spec["height_px"]) == size
    assert len(spec["slots"]) == slots
    assert spec["outputs_per_session"] == 1


@pytest.mark.parametrize(
    "path",
    [
        "/api/templates/unknown",
        "/api/templates/strip_2x6?version=9",
        "/api/templates/unknown/guide.png",
        "/api/templates/strip_2x6/blank.png?version=2",
        "/api/render/samples/strip_2x6/3.jpg",
        "/api/render/samples/unknown/1.jpg",
    ],
)
def test_unknown_template_version_or_output_is_404(kiosk_client: TestClient, path: str) -> None:
    assert kiosk_client.get(path).status_code == 404


def test_bad_key_format_is_rejected(kiosk_client: TestClient) -> None:
    assert kiosk_client.get("/api/templates/STRIP..").status_code in (404, 422)


def _png(response_bytes: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(response_bytes))
    image.load()
    return image


@pytest.mark.parametrize(
    ("key", "size"),
    [("strip_2x6", (600, 1800)), ("print_3x4", (900, 1200)), ("print_4x6", (1200, 1800))],
)
def test_blank_png_is_exact_size_transparent_rgba_at_300_dpi(
    kiosk_client: TestClient, key: str, size: tuple[int, int]
) -> None:
    response = kiosk_client.get(f"/api/templates/{key}/blank.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    image = _png(response.content)
    assert image.format == "PNG" and image.mode == "RGBA"
    assert image.size == size
    assert tuple(round(v) for v in image.info["dpi"]) == (300, 300)
    assert image.getextrema()[3] == (0, 0)  # fully transparent


@pytest.mark.parametrize(
    ("key", "size"),
    [("strip_2x6", (600, 1800)), ("print_3x4", (900, 1200)), ("print_4x6", (1200, 1800))],
)
def test_guide_png_marks_slots_at_their_coordinates(
    kiosk_client: TestClient, key: str, size: tuple[int, int]
) -> None:
    spec = kiosk_client.get(f"/api/templates/{key}").json()
    response = kiosk_client.get(f"/api/templates/{key}/guide.png")
    assert response.status_code == 200
    image = _png(response.content).convert("RGBA")
    assert image.size == size
    for slot in spec["slots"]:
        # Just inside each slot corner (away from centered labels) the slot fill color is drawn.
        inner = (slot["x"] + slot["w"] // 5, slot["y"] + slot["h"] // 8)
        assert image.getpixel(inner) == SLOT_FILL, (key, slot["index"])
        outside = (slot["x"] - 1, slot["y"] + slot["h"] // 8)
        assert image.getpixel(outside) != SLOT_FILL


def test_sample_render_endpoint(kiosk_client: TestClient) -> None:
    response = kiosk_client.get("/api/render/samples/strip_2x6/2.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-photobooth-capture-ids"] == "sample-4,sample-5,sample-6"
    image = _png(response.content)
    assert image.size == (600, 1800)
    assert tuple(round(v) for v in image.info["dpi"]) == (300, 300)


def test_template_routes_are_read_only(kiosk_client: TestClient) -> None:
    assert kiosk_client.post("/api/templates/strip_2x6").status_code == 405
    assert kiosk_client.delete("/api/templates/strip_2x6").status_code == 405
