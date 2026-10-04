"""The server draws a decoration the way the booth previews it.

Filters: every colour of the shared parity fixture comes out of Pillow as the booth's SVG
feColorMatrix makes it (the frontend checks the same fixture). Stickers: placed by their centre,
sized by the photo's width, turned clockwise, clipped at the edge, on top of the frame.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from photobooth.modules.decorations.builtin import BUILTIN_STICKERS, PackagedStickerLibrary
from photobooth.modules.decorations.domain import FILTERS
from photobooth.modules.rendering.domain import (
    CaptureRef,
    Decoration,
    RenderJob,
    StickerPlacement,
    plan_outputs,
)
from photobooth.modules.rendering.renderer import (
    PillowPhotoRenderer,
    _filtered,
    _place_sticker,
)
from photobooth.modules.templates.repository import JsonTemplateRepository

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "decoration_parity.json").read_text(
        encoding="utf-8"
    )
)
RED = (220, 30, 40, 255)


def png(size: tuple[int, int], colour: tuple[int, int, int, int] = RED) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_parity_fixture_holds_the_filters_the_server_offers() -> None:
    assert FIXTURE["filters"] == {preset.key: list(preset.matrix) for preset in FILTERS}


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: f"{c['filter']}-{c['input']}")
def test_pillow_colours_each_fixture_colour_as_the_booth_does(case: dict[str, object]) -> None:
    matrix = tuple(FIXTURE["filters"][case["filter"]])
    pixel = Image.new("RGB", (1, 1), tuple(case["input"]))  # type: ignore[arg-type]
    out = _filtered(pixel, None if case["filter"] == "none" else matrix).getpixel((0, 0))
    assert isinstance(out, tuple)
    for got, want in zip(out, case["expected"], strict=True):  # type: ignore[call-overload]
        assert abs(got - want) <= 1, (case, out)


def _canvas() -> Image.Image:
    return Image.new("RGBA", (1000, 500), (255, 255, 255, 255))


def test_a_sticker_is_centred_and_sized_by_the_photos_width() -> None:
    canvas = _canvas()
    _place_sticker(canvas, StickerPlacement(png((100, 50)), x=0.5, y=0.5, size=0.2, rotation=0))
    # 200 x 100 around (500, 250): x 400..599, y 200..299.
    assert canvas.getpixel((402, 202)) == RED
    assert canvas.getpixel((597, 297)) == RED
    assert canvas.getpixel((395, 250)) == (255, 255, 255, 255)
    assert canvas.getpixel((500, 305)) == (255, 255, 255, 255)


def test_a_sticker_turns_clockwise_as_the_booth_shows_it() -> None:
    canvas = _canvas()
    art = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
    art.paste(RED, (0, 0, 50, 50))  # the left half is red
    buffer = io.BytesIO()
    art.save(buffer, format="PNG")
    _place_sticker(canvas, StickerPlacement(buffer.getvalue(), x=0.5, y=0.5, size=0.2, rotation=90))
    # Turned a quarter clockwise, the left half points up: 100 x 200 around (500, 250).
    assert canvas.getpixel((500, 170)) == RED
    assert canvas.getpixel((500, 330)) == (255, 255, 255, 255)
    assert canvas.getpixel((570, 250)) == (255, 255, 255, 255)


def _red_box(canvas: Image.Image) -> tuple[int, int, int, int]:
    box = canvas.convert("RGB").point(lambda v: 255 if v < 128 else 0).getbbox()
    # Only the red sticker has a channel below 128 (green and blue are 30 and 40).
    assert box is not None
    return box


def test_a_sticker_resized_by_its_handle_grows_in_place_keeping_its_shape() -> None:
    """The booth's Resize handle changes only the size: the server keeps the centre and the
    sticker's own aspect ratio, as the preview shows (handles themselves are never drawn)."""
    art = png((120, 60))
    small, large = _canvas(), _canvas()
    _place_sticker(small, StickerPlacement(art, x=0.4, y=0.6, size=0.2, rotation=0))
    _place_sticker(large, StickerPlacement(art, x=0.4, y=0.6, size=0.32, rotation=0))
    (a0, b0, a1, b1), (c0, d0, c1, d1) = _red_box(small), _red_box(large)
    assert (a1 - a0, b1 - b0) == (200, 100)  # 0.2 of 1000 wide, half as tall
    assert (c1 - c0, d1 - d0) == (320, 160)  # 0.32: the same 2:1 shape
    assert ((a0 + a1) / 2, (b0 + b1) / 2) == ((c0 + c1) / 2, (d0 + d1) / 2) == (400, 300)


def test_a_sticker_over_the_edge_is_cut_off_there() -> None:
    canvas = _canvas()
    _place_sticker(canvas, StickerPlacement(png((100, 100)), x=0.0, y=1.0, size=0.2, rotation=30))
    assert canvas.getpixel((5, 495)) == RED
    assert canvas.getpixel((500, 250)) == (255, 255, 255, 255)
    assert canvas.size == (1000, 500)


def test_stickers_lie_on_the_frame_and_the_filter_colours_the_photos_only() -> None:
    template = JsonTemplateRepository().get("print_3x4")
    captures = [CaptureRef(capture_id=f"c{n}", shot_index=n) for n in (1, 2)]
    plan = plan_outputs(template, captures)[0]
    photo = io.BytesIO()
    Image.new("RGB", (1280, 720), (30, 160, 220)).save(photo, format="JPEG", quality=95)
    frame = Image.new("RGBA", (template.width_px, template.height_px), (250, 240, 10, 255))
    for defined in template.slots:
        hole = defined.rect
        frame.paste((0, 0, 0, 0), (hole.x, hole.y, hole.x + hole.w, hole.y + hole.h))
    slot = template.slots[0].rect
    frame_png = io.BytesIO()
    frame.save(frame_png, format="PNG")
    mono = next(p for p in FILTERS if p.key == "mono").matrix

    out = PillowPhotoRenderer().render(
        RenderJob(
            template=template,
            plan=plan,
            images={"c1": photo.getvalue(), "c2": photo.getvalue()},
            frame_png=frame_png.getvalue(),
            decoration=Decoration(
                color_matrix=mono,
                stickers=(StickerPlacement(png((50, 50)), x=0.05, y=0.05, size=0.06, rotation=0),),
            ),
        )
    )
    image = Image.open(io.BytesIO(out.data)).convert("RGB")
    r, g, b = image.getpixel((slot.x + slot.w // 2, slot.y + slot.h // 2))
    assert max(r, g, b) - min(r, g, b) <= 3  # the photo is black and white
    fr, fg, fb = image.getpixel((template.width_px - 5, template.height_px - 5))
    assert fr > 230 and fg > 220 and fb < 40  # the frame keeps its own yellow
    sr, sg, sb = image.getpixel((round(0.05 * template.width_px), round(0.05 * template.height_px)))
    assert sr > 190 and sg < 70 and sb < 80  # the sticker lies on the frame


def test_every_builtin_sticker_is_a_transparent_srgb_png() -> None:
    library = PackagedStickerLibrary()
    offered = library.stickers()
    assert [s.key for s in offered] == [s.key for s in BUILTIN_STICKERS]
    for sticker in offered:
        image = Image.open(io.BytesIO(library.png(sticker.key)))
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.size == (sticker.width, sticker.height)
        assert 64 <= max(image.size) <= 1024
        assert "icc_profile" not in image.info
        alpha = image.getchannel("A")
        assert alpha.getextrema() == (0, 255)  # a cut-out with a solid body
