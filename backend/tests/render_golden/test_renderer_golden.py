"""Golden renderer tests: pixel sampling of real Pillow output (tolerant to JPEG noise)."""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageCms

from photobooth.modules.rendering.domain import CaptureRef, RenderError
from photobooth.modules.rendering.queue import RenderQueue
from photobooth.modules.rendering.renderer import (
    MAX_INPUT_PIXELS,
    PillowPhotoRenderer,
    PillowSampleImageFactory,
)
from photobooth.modules.rendering.service import RenderService
from photobooth.modules.templates.imaging import PillowTemplateArtist
from photobooth.modules.templates.repository import JsonTemplateRepository
from photobooth.modules.templates.service import TemplateSpecService

TEMPLATES = JsonTemplateRepository()
SERVICE = RenderService(
    PillowPhotoRenderer(),
    TemplateSpecService(TEMPLATES, PillowTemplateArtist()),
    PillowSampleImageFactory(),
    RenderQueue(max_pending=4),
)
COLORS = {
    1: (220, 30, 30),
    2: (30, 180, 60),
    3: (40, 80, 220),
    4: (240, 200, 20),
    5: (150, 60, 180),
    6: (20, 190, 190),
}
TOLERANCE = 12


def _solid(color: tuple[int, int, int], size: tuple[int, int] = (1280, 720)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class DictSource:
    def __init__(self, images: dict[str, bytes]) -> None:
        self.images = images

    def read(self, capture_id: str) -> bytes:
        return self.images[capture_id]


def _session(count: int) -> tuple[list[CaptureRef], DictSource]:
    captures = [CaptureRef(f"cap-{i}", i) for i in range(1, count + 1)]
    return captures, DictSource({f"cap-{i}": _solid(COLORS[i]) for i in range(1, count + 1)})


def _decode(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def _close(actual: tuple[int, ...], expected: tuple[int, int, int]) -> bool:
    return all(abs(a - e) <= TOLERANCE for a, e in zip(actual[:3], expected, strict=True))


def _center(rect: object) -> tuple[int, int]:
    return (rect.x + rect.w // 2, rect.y + rect.h // 2)  # type: ignore[attr-defined]


@pytest.mark.parametrize(("key", "count"), [("strip_2x6", 6), ("print_3x4", 2), ("print_4x6", 4)])
def test_output_dimensions_dpi_format_and_srgb(key: str, count: int) -> None:
    template = TEMPLATES.get(key)
    captures, source = _session(count)
    outputs = SERVICE.render_session(template, captures, source)
    assert len(outputs) == template.outputs_per_session
    for output in outputs:
        image = _decode(output.data)
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (template.width_px, template.height_px)
        dpi = image.info["dpi"]
        assert round(dpi[0]) == 300 and round(dpi[1]) == 300
        profile = ImageCms.ImageCmsProfile(io.BytesIO(image.info["icc_profile"]))
        assert "sRGB" in ImageCms.getProfileDescription(profile)
        assert (output.width, output.height, output.dpi) == (
            template.width_px,
            template.height_px,
            300,
        )
        assert output.media_type == "image/jpeg"


@pytest.mark.parametrize(("key", "count"), [("strip_2x6", 6), ("print_3x4", 2), ("print_4x6", 4)])
def test_each_slot_shows_its_capture_and_background_stays_white(key: str, count: int) -> None:
    template = TEMPLATES.get(key)
    captures, source = _session(count)
    outputs = SERVICE.render_session(template, captures, source)
    for output, group in zip(outputs, template.output_capture_groups, strict=True):
        image = _decode(output.data)
        for slot, shot in zip(template.slots, group, strict=True):
            r = slot.rect
            for point in (_center(r), (r.x + 4, r.y + 4), (r.right - 5, r.bottom - 5)):
                assert _close(image.getpixel(point), COLORS[shot]), (key, slot.index, point)
        # A point in the gap/margin outside every slot is canvas background (white).
        top_left = (5, 5)
        assert _close(image.getpixel(top_left), (255, 255, 255))


def test_2x6_strips_never_reuse_a_capture() -> None:
    template = TEMPLATES.get("strip_2x6")
    captures, source = _session(6)
    strip1, strip2 = SERVICE.render_session(template, captures, source)
    assert strip1.capture_ids == ("cap-1", "cap-2", "cap-3")
    assert strip2.capture_ids == ("cap-4", "cap-5", "cap-6")
    assert set(strip1.capture_ids).isdisjoint(strip2.capture_ids)
    assert set(strip1.capture_ids) | set(strip2.capture_ids) == {c.capture_id for c in captures}

    seen = []
    for strip, own_shots in ((strip1, (1, 2, 3)), (strip2, (4, 5, 6))):
        image = _decode(strip.data)
        found = {
            shot
            for slot in template.slots
            for shot in COLORS
            if _close(image.getpixel(_center(slot.rect)), COLORS[shot])
        }
        assert found == set(own_shots)
        seen.append(found)
    assert seen[0].isdisjoint(seen[1])


def test_cover_crop_is_centered_and_fills_the_slot() -> None:
    """16:9 capture with 60 px red side bands: a 3:2 slot center-crops them away completely."""
    template = TEMPLATES.get("print_3x4")
    image = Image.new("RGB", (1600, 900), (0, 200, 0))
    for x0 in (0, 1600 - 60):
        image.paste((255, 0, 0), (x0, 0, x0 + 60, 900))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    captures = [CaptureRef("a", 1), CaptureRef("b", 2)]
    source = DictSource({"a": buffer.getvalue(), "b": buffer.getvalue()})
    (output,) = SERVICE.render_session(template, captures, source)
    rendered = _decode(output.data)
    slot = template.slots[0].rect
    for point in ((slot.x + 2, slot.y + slot.h // 2), (slot.right - 3, slot.y + slot.h // 2)):
        assert _close(rendered.getpixel(point), (0, 200, 0)), point


def test_mirror_flips_the_photo_horizontally() -> None:
    template = TEMPLATES.get("print_3x4")
    left_red = Image.new("RGB", (1500, 1000), (0, 0, 255))
    left_red.paste((255, 0, 0), (0, 0, 750, 1000))
    buffer = io.BytesIO()
    left_red.save(buffer, format="PNG")
    captures = [CaptureRef("a", 1), CaptureRef("b", 2)]
    source = DictSource({"a": buffer.getvalue(), "b": buffer.getvalue()})
    slot = template.slots[0].rect
    left_point = (slot.x + 40, slot.y + slot.h // 2)
    (normal,) = SERVICE.render_session(template, captures, source)
    (mirrored,) = SERVICE.render_session(template, captures, source, mirror=True)
    assert _close(_decode(normal.data).getpixel(left_point), (255, 0, 0))
    assert _close(_decode(mirrored.data).getpixel(left_point), (0, 0, 255))


def test_frame_png_is_composited_over_photos() -> None:
    template = TEMPLATES.get("strip_2x6")
    frame = Image.new("RGBA", (600, 1800), (255, 0, 255, 255))
    for slot in template.slots:
        r = slot.rect
        frame.paste((0, 0, 0, 0), (r.x, r.y, r.right, r.bottom))
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG")
    captures, source = _session(6)
    strip1, _ = SERVICE.render_session(template, captures, source, frame_png=buffer.getvalue())
    image = _decode(strip1.data)
    assert _close(image.getpixel((5, 5)), (255, 0, 255))  # frame border
    assert _close(image.getpixel((300, 1600)), (255, 0, 255))  # branding area painted by frame
    assert _close(image.getpixel(_center(template.slots[1].rect)), COLORS[2])  # photo shows through


def test_frame_with_wrong_size_is_rejected() -> None:
    template = TEMPLATES.get("print_3x4")
    buffer = io.BytesIO()
    Image.new("RGBA", (899, 1200), (0, 0, 0, 0)).save(buffer, format="PNG")
    captures, source = _session(2)
    with pytest.raises(RenderError, match="frame must be 900x1200"):
        SERVICE.render_session(template, captures, source, frame_png=buffer.getvalue())


def test_unreadable_and_oversized_inputs_are_rejected() -> None:
    template = TEMPLATES.get("print_3x4")
    captures = [CaptureRef("a", 1), CaptureRef("b", 2)]
    with pytest.raises(RenderError, match="not a readable image"):
        SERVICE.render_session(template, captures, DictSource({"a": b"not an image", "b": b"x"}))
    side = int(MAX_INPUT_PIXELS**0.5) + 10
    buffer = io.BytesIO()
    Image.new("L", (side, side), 0).save(buffer, format="PNG")
    huge = buffer.getvalue()
    with pytest.raises(RenderError, match=r"too large|not a readable image"):
        SERVICE.render_session(template, captures, DictSource({"a": huge, "b": huge}))


def test_sample_preview_uses_numbered_unique_captures_per_strip() -> None:
    strip2 = SERVICE.render_sample("strip_2x6", 2).result(timeout=60)
    assert strip2.capture_ids == ("sample-4", "sample-5", "sample-6")
    assert _decode(strip2.data).size == (600, 1800)
    with pytest.raises(RenderError):
        SERVICE.render_sample("strip_2x6", 3)


# --- colour management (P2-R02) -------------------------------------------------------------


def _tagged(
    color: tuple[int, int, int], mode: str = "RGB", size: tuple[int, int] = (1200, 900)
) -> bytes:
    from tests.render_golden.icc import adobe_rgb_profile

    buffer = io.BytesIO()
    Image.new(mode, size, color if mode == "RGB" else (*color, 255)).save(
        buffer, format="PNG", icc_profile=adobe_rgb_profile()
    )
    return buffer.getvalue()


def _expected_srgb(color: tuple[int, int, int]) -> tuple[int, ...]:
    from tests.render_golden.icc import adobe_rgb_profile

    source = ImageCms.ImageCmsProfile(io.BytesIO(adobe_rgb_profile()))
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    converted = ImageCms.profileToProfile(
        Image.new("RGB", (1, 1), color),
        source,
        srgb,
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        outputMode="RGB",
    )
    assert converted is not None
    return tuple(converted.getpixel((0, 0)))


def test_tagged_wide_gamut_capture_is_converted_to_srgb_not_relabelled() -> None:
    template = TEMPLATES.get("print_3x4")
    adobe_green = (40, 200, 40)
    expected = _expected_srgb(adobe_green)
    assert not _close(expected, adobe_green)  # the conversion is material for this colour
    captures = [CaptureRef("a", 1), CaptureRef("b", 2)]
    tagged = _tagged(adobe_green)
    (output,) = SERVICE.render_session(template, captures, DictSource({"a": tagged, "b": tagged}))
    pixel = _decode(output.data).getpixel(_center(template.slots[0].rect))
    assert _close(pixel, expected), (pixel, expected)  # type: ignore[arg-type]
    assert not _close(pixel, adobe_green)


def test_tagged_frame_is_converted_and_keeps_its_transparency() -> None:
    from tests.render_golden.icc import adobe_rgb_profile

    template = TEMPLATES.get("print_3x4")
    border = (180, 60, 120)
    frame = Image.new("RGBA", (900, 1200), (*border, 255))
    for slot in template.slots:
        r = slot.rect
        frame.paste((0, 0, 0, 0), (r.x, r.y, r.right, r.bottom))
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG", icc_profile=adobe_rgb_profile())
    captures, source = _session(2)
    (output,) = SERVICE.render_session(template, captures, source, frame_png=buffer.getvalue())
    image = _decode(output.data)
    assert _close(image.getpixel((5, 5)), _expected_srgb(border))  # type: ignore[arg-type]
    assert _close(image.getpixel(_center(template.slots[0].rect)), COLORS[1])


def test_untagged_cmyk_and_broken_profiles_are_rejected() -> None:
    template = TEMPLATES.get("print_3x4")
    captures = [CaptureRef("a", 1), CaptureRef("b", 2)]
    cmyk = io.BytesIO()
    Image.new("CMYK", (800, 600), (0, 100, 100, 0)).save(cmyk, format="JPEG")
    with pytest.raises(RenderError, match="CMYK without an ICC profile"):
        SERVICE.render_session(
            template, captures, DictSource({"a": cmyk.getvalue(), "b": cmyk.getvalue()})
        )
    broken = io.BytesIO()
    Image.new("RGB", (800, 600), (1, 2, 3)).save(broken, format="PNG", icc_profile=b"not a profile")
    with pytest.raises(RenderError, match="ICC profile"):
        SERVICE.render_session(
            template, captures, DictSource({"a": broken.getvalue(), "b": broken.getvalue()})
        )
