"""P2-R01: every guide image carries ALL required annotations, inside the canvas and safe area."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from photobooth.modules.templates.imaging import guide_annotations, layout_guide_info
from photobooth.modules.templates.repository import JsonTemplateRepository

TEMPLATES = JsonTemplateRepository()


@pytest.mark.parametrize("key", ["strip_2x6", "print_3x4", "print_4x6"])
def test_all_required_annotations_are_laid_out(key: str) -> None:
    template = TEMPLATES.get(key)
    draw = ImageDraw.Draw(Image.new("RGBA", (template.width_px, template.height_px)))
    layout = layout_guide_info(template, draw)
    required = guide_annotations(template)
    assert list(layout.lines) == required  # nothing dropped
    text = "\n".join(layout.lines)
    assert f"{template.width_px} x {template.height_px} px | {template.dpi} DPI" in text
    assert "PNG RGBA" in text and "95% transparent" in text
    assert "safe area (36 px margin)" in text
    safe = template.safe_area
    area = layout.area
    assert safe.x <= area.x and safe.y <= area.y
    assert area.right <= safe.right and area.bottom <= safe.bottom
    assert layout.font_size >= 9


def test_3x4_without_branding_area_uses_a_panel_inside_the_last_photo() -> None:
    template = TEMPLATES.get("print_3x4")
    draw = ImageDraw.Draw(Image.new("RGBA", (900, 1200)))
    layout = layout_guide_info(template, draw)
    last = template.slots[-1].rect
    assert layout.panel
    assert last.x < layout.area.x and layout.area.right < last.right
    assert last.y < layout.area.y and layout.area.bottom <= last.bottom


def test_2x6_annotations_include_capture_split() -> None:
    lines = guide_annotations(TEMPLATES.get("strip_2x6"))
    assert "6 captures -> 2 outputs, no photo reused" in lines
    assert lines[0] == "BRANDING AREA (yellow)"
