"""Pillow implementation of TemplateArtist: blank frame canvas and labeled guide image."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from photobooth.modules.templates.domain import PhotoTemplate, Rect

BACKGROUND = (246, 246, 246, 255)
SLOT_FILL = (176, 204, 236, 255)
SLOT_EDGE = (32, 74, 135, 255)
SAFE_EDGE = (214, 40, 40, 255)
BRANDING_FILL = (255, 236, 179, 255)
BRANDING_EDGE = (184, 134, 11, 255)
TEXT = (20, 20, 20, 255)


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
            _centered_lines(
                draw,
                r,
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

        info = [
            (f"{template.name}  (v{template.version})", _font(int(unit * 1.1))),
            (
                f"{_num(template.width_in)} x {_num(template.height_in)} in  |  "
                f"{width} x {height} px  |  {template.dpi} DPI",
                _font(int(unit * 0.8)),
            ),
            (
                f"Frame: PNG RGBA, photo areas >= "
                f"{round(template.frame_rules.slot_min_transparency * 100)}% transparent",
                _font(int(unit * 0.8)),
            ),
            (
                f"Red dashed line = safe area ({template.safe_area_inset} px margin)",
                _font(int(unit * 0.8)),
            ),
        ]
        if template.outputs_per_session > 1:
            info.append(
                (
                    f"{template.captures_per_session} captures -> "
                    f"{template.outputs_per_session} outputs, no photo reused",
                    _font(int(unit * 0.8)),
                )
            )
        info_area = _intersect(
            template.branding_area or _bottom_margin(template), template.safe_area
        )
        if template.branding_area is not None:
            info.insert(0, ("BRANDING AREA", _font(int(unit * 1.2))))
        gap = max(2, unit // 4)
        _centered_lines(draw, info_area, _fit(draw, info, info_area, gap), gap=gap)
        return _png(image, template.dpi)


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _intersect(a: Rect, b: Rect) -> Rect:
    x, y = max(a.x, b.x), max(a.y, b.y)
    right, bottom = min(a.right, b.right), min(a.bottom, b.bottom)
    return Rect(x, y, max(0, right - x), max(0, bottom - y))


def _bottom_margin(template: PhotoTemplate) -> Rect:
    top = max(slot.rect.bottom for slot in template.slots)
    return Rect(0, top, template.width_px, template.height_px - top)


def _fit(
    draw: ImageDraw.ImageDraw,
    lines: list[tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]],
    area: Rect,
    gap: int,
) -> list[tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]]:
    """Keep only the lines that fit inside the area with margins (most important first)."""
    kept: list[tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]] = []
    used: float = 0
    margin = 2 * gap + 8
    for text, font in lines:
        box = draw.textbbox((0, 0), text, font=font)
        height = box[3] - box[1] + (gap if kept else 0)
        if used + height > area.h - margin or box[2] - box[0] > area.w - margin:
            if not kept:
                continue
            break
        kept.append((text, font))
        used += height
    return kept
