"""Pillow implementation of TemplateArtist: blank frame canvas and labeled guide image."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from photobooth.modules.templates.domain import PhotoTemplate, Rect

BACKGROUND = (246, 246, 246, 255)
SLOT_FILL = (176, 204, 236, 255)
SLOT_EDGE = (32, 74, 135, 255)
SAFE_EDGE = (214, 40, 40, 255)
BRANDING_FILL = (255, 236, 179, 255)
BRANDING_EDGE = (184, 134, 11, 255)
TEXT = (20, 20, 20, 255)
PANEL_FILL = (255, 255, 255, 235)


def _png(image: Image.Image, dpi: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(dpi, dpi), optimize=True)
    return buffer.getvalue()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _dashed_rect(draw: ImageDraw.ImageDraw, rect: Rect, color: tuple[int, ...], width: int) -> None:
    dash = max(6, width * 4)
    for start in range(rect.x, rect.right, dash * 2):
        end = min(start + dash, rect.right)
        draw.line([(start, rect.y), (end, rect.y)], fill=color, width=width)
        draw.line([(start, rect.bottom - 1), (end, rect.bottom - 1)], fill=color, width=width)
    for start in range(rect.y, rect.bottom, dash * 2):
        end = min(start + dash, rect.bottom)
        draw.line([(rect.x, start), (rect.x, end)], fill=color, width=width)
        draw.line([(rect.right - 1, start), (rect.right - 1, end)], fill=color, width=width)


def _centered_lines(
    draw: ImageDraw.ImageDraw,
    rect: Rect,
    lines: list[tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]],
    gap: int,
) -> None:
    sizes = [draw.textbbox((0, 0), text, font=font) for text, font in lines]
    heights = [box[3] - box[1] for box in sizes]
    total = sum(heights) + gap * (len(lines) - 1)
    y = rect.y + (rect.h - total) / 2
    for (text, font), box, height in zip(lines, sizes, heights, strict=True):
        width = box[2] - box[0]
        draw.text((rect.x + (rect.w - width) / 2 - box[0], y - box[1]), text, font=font, fill=TEXT)
        y += height + gap


class PillowTemplateArtist:
    """Draws specification images at exact canvas size with the template DPI embedded."""

    def blank_png(self, template: PhotoTemplate) -> bytes:
        image = Image.new("RGBA", (template.width_px, template.height_px), (0, 0, 0, 0))
        return _png(image, template.dpi)

    def guide_png(self, template: PhotoTemplate) -> bytes:
        width, height = template.width_px, template.height_px
        unit = max(12, width // 30)
        image = Image.new("RGBA", (width, height), BACKGROUND)
        draw = ImageDraw.Draw(image)
        line = max(2, unit // 8)
        info = layout_guide_info(template, draw)

        if template.branding_area is not None:
            area = template.branding_area
            draw.rectangle(
                [area.x, area.y, area.right - 1, area.bottom - 1],
                fill=BRANDING_FILL,
                outline=BRANDING_EDGE,
                width=line,
            )

        for slot in template.slots:
            r = slot.rect
            draw.rectangle(
                [r.x, r.y, r.right - 1, r.bottom - 1], fill=SLOT_FILL, outline=SLOT_EDGE, width=line
            )
            label_area = r
            if info.panel and slot.index == template.slots[-1].index:
                label_area = Rect(r.x, r.y, r.w, info.area.y - r.y)
            _centered_lines(
                draw,
                label_area,
                [
                    (f"PHOTO {slot.index}", _font(int(unit * 2.2))),
                    (f"{r.w} x {r.h} px ({slot.aspect_label})", _font(unit)),
                    (f"x={r.x}  y={r.y}", _font(unit)),
                    ("transparent in frame PNG", _font(int(unit * 0.8))),
                ],
                gap=unit // 2,
            )

        # Safe area on top so it stays visible; photo slots may extend past it by design.
        _dashed_rect(draw, template.safe_area, SAFE_EDGE, line)
        draw.rectangle([0, 0, width - 1, height - 1], outline=TEXT, width=line)

        if info.panel:
            a = info.area
            draw.rectangle(
                [a.x, a.y, a.right - 1, a.bottom - 1], fill=PANEL_FILL, outline=TEXT, width=1
            )
        font = _font(info.font_size)
        _centered_lines(draw, info.area, [(text, font) for text in info.lines], gap=info.gap)
        return _png(image, template.dpi)


def guide_annotations(template: PhotoTemplate) -> list[str]:
    """Required text on every guide image (also asserted by tests)."""
    lines = [
        f"{template.name} (v{template.version})",
        f"{_num(template.width_in)} x {_num(template.height_in)} in | "
        f"{template.width_px} x {template.height_px} px | {template.dpi} DPI",
        f"Frame: PNG RGBA, photo areas >= "
        f"{round(template.frame_rules.slot_min_transparency * 100)}% transparent",
        f"Red dashed line = safe area ({template.safe_area_inset} px margin)",
    ]
    if template.branding_area is not None:
        lines.insert(0, "BRANDING AREA (yellow)")
    if template.outputs_per_session > 1:
        lines.append(
            f"{template.captures_per_session} captures -> "
            f"{template.outputs_per_session} outputs, no photo reused"
        )
    return lines


@dataclass(frozen=True)
class GuideInfoLayout:
    area: Rect
    panel: bool
    font_size: int
    gap: int
    lines: tuple[str, ...]


def layout_guide_info(template: PhotoTemplate, draw: ImageDraw.ImageDraw) -> GuideInfoLayout:
    """Place ALL required annotations: branding area, then bottom margin, then a panel inside the
    last photo placeholder. Fonts shrink step by step; nothing is ever silently dropped."""
    lines = guide_annotations(template)
    unit = max(12, template.width_px // 30)
    safe = template.safe_area
    candidates: list[tuple[Rect, bool]] = []
    if template.branding_area is not None:
        candidates.append((_intersect(template.branding_area, safe), False))
    candidates.append((_intersect(_bottom_margin(template), safe), False))
    last = template.slots[-1].rect
    panel_height = int(last.h * 0.42)
    inset = max(6, unit // 3)
    candidates.append(
        (
            Rect(
                last.x + inset, last.bottom - panel_height, last.w - 2 * inset, panel_height - inset
            ),
            True,
        )
    )
    minimum = max(9, int(unit * 0.4))
    for area, panel in candidates:
        size = int(unit * 0.8)
        while size >= minimum:
            gap = max(2, size // 4)
            if _all_fit(draw, lines, _font(size), area, gap):
                return GuideInfoLayout(area, panel, size, gap, tuple(lines))
            size -= 1
    raise ValueError(f"guide annotations do not fit for {template.key}")


def _all_fit(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    area: Rect,
    gap: int,
) -> bool:
    margin = 2 * gap + 8
    boxes = [draw.textbbox((0, 0), text, font=font) for text in lines]
    total = sum(b[3] - b[1] for b in boxes) + gap * (len(lines) - 1)
    widest = max(b[2] - b[0] for b in boxes)
    return total <= area.h - margin and widest <= area.w - margin


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _intersect(a: Rect, b: Rect) -> Rect:
    x, y = max(a.x, b.x), max(a.y, b.y)
    right, bottom = min(a.right, b.right), min(a.bottom, b.bottom)
    return Rect(x, y, max(0, right - x), max(0, bottom - y))


def _bottom_margin(template: PhotoTemplate) -> Rect:
    top = max(slot.rect.bottom for slot in template.slots)
    return Rect(0, top, template.width_px, template.height_px - top)
