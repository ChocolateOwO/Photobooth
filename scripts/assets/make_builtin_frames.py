"""Draw the packaged built-in frame PNGs (offline, deterministic).

Run from the repository root with the backend virtualenv:
    backend\\.venv\\Scripts\\python.exe scripts\\assets\\make_builtin_frames.py

Each frame is drawn at twice the size and reduced for smooth edges, then every photo slot is cleared
to full transparency, saved without a colour profile and checked with the same validator that
checks uploaded frames. The web app never draws or edits frames.
"""

from __future__ import annotations

import math
import random
import sys
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from photobooth.modules.frames.builtin import (
    BUILTIN_DIRECTORY,
    BUILTIN_TEMPLATE_VERSION,
    builtin_frames,
)
from photobooth.modules.frames.validator import PillowFrameValidator
from photobooth.modules.templates.domain import PhotoTemplate, Rect
from photobooth.modules.templates.repository import JsonTemplateRepository

SS = 2  # supersampling factor
RGBA = tuple[int, int, int, int]


def _scaled(rect: Rect, grow: int = 0) -> tuple[int, int, int, int]:
    return (
        (rect.x - grow) * SS,
        (rect.y - grow) * SS,
        (rect.x + rect.w + grow) * SS - 1,
        (rect.y + rect.h + grow) * SS - 1,
    )


def _vertical_gradient(size: tuple[int, int], top: RGBA, bottom: RGBA) -> Image.Image:
    width, height = size
    column = Image.new("RGBA", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        column.putpixel(
            (0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        )
    return column.resize((width, height))


def _footer_band(template: PhotoTemplate) -> tuple[int, int]:
    """(top, bottom) of the free band under the last slot, at 1x."""
    last = max(slot.rect.y + slot.rect.h for slot in template.slots)
    return last, template.height_px


def _in_margin(template: PhotoTemplate, x: float, y: float, pad: int) -> bool:
    return not any(
        slot.rect.x - pad <= x <= slot.rect.x + slot.rect.w + pad
        and slot.rect.y - pad <= y <= slot.rect.y + slot.rect.h + pad
        for slot in template.slots
    )


def draw_minimal_light(template: PhotoTemplate) -> Image.Image:
    w, h = template.width_px * SS, template.height_px * SS
    image = Image.new("RGBA", (w, h), (250, 249, 246, 255))
    draw = ImageDraw.Draw(image)
    inset = 12 * SS
    draw.rectangle(
        (inset, inset, w - inset - 1, h - inset - 1), outline=(226, 222, 214, 255), width=SS
    )
    for slot in template.slots:
        draw.rectangle(_scaled(slot.rect, 4), outline=(196, 190, 180, 255), width=2 * SS)
    top, bottom = _footer_band(template)
    band = bottom - top
    cy = (top + bottom) / 2 * SS
    cx = w / 2
    line = min(w * 0.3, 240 * SS)
    ink = (168, 160, 148, 255)
    if band >= 80:
        ring = min(band * 0.17, 64) * SS
        draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=ink, width=2 * SS)
        inner = ring * 0.78
        draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), outline=ink, width=SS)
        draw.line((cx - line, cy, cx - ring - 10 * SS, cy), fill=ink, width=2 * SS)
        draw.line((cx + ring + 10 * SS, cy, cx + line, cy), fill=ink, width=2 * SS)
        for dx, r in ((-0.32, 0.06), (0, 0.1), (0.32, 0.06)):
            x, rr = cx + dx * ring, r * ring
            draw.ellipse((x - rr, cy - rr, x + rr, cy + rr), fill=ink)
    else:
        draw.line((cx - line, cy, cx + line, cy), fill=(200, 194, 184, 255), width=SS)
    return image


def draw_midnight(template: PhotoTemplate) -> Image.Image:
    w, h = template.width_px * SS, template.height_px * SS
    image = _vertical_gradient((w, h), (9, 16, 34, 255), (30, 44, 82, 255))
    rng = random.Random(f"midnight/{template.key}")  # noqa: S311 - repeatable art, not security
    stars = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(stars)
    count = template.width_px * template.height_px // 2600
    for _ in range(count):
        x, y = rng.uniform(0, template.width_px), rng.uniform(0, template.height_px)
        if not _in_margin(template, x, y, 8):
            continue
        r = rng.choice((0.8, 1.0, 1.2, 1.6, 2.2))
        alpha = rng.randint(120, 235)
        sdraw.ellipse(
            ((x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS), fill=(255, 255, 255, alpha)
        )
    image.alpha_composite(stars)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for slot in template.slots:
        gdraw.rectangle(_scaled(slot.rect, 5), outline=(120, 160, 255, 150), width=6 * SS)
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6 * SS)))
    draw = ImageDraw.Draw(image)
    for slot in template.slots:
        draw.rectangle(_scaled(slot.rect, 3), outline=(170, 192, 240, 255), width=2 * SS)
    top, bottom = _footer_band(template)
    band = bottom - top
    if band >= 80:
        cx, cy = w / 2, (top + bottom) / 2 * SS
        r = min(band * 0.26, 96) * SS
        moon = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        mdraw = ImageDraw.Draw(moon)
        mdraw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(246, 234, 186, 255))
        mdraw.ellipse(
            (cx - r * 0.55, cy - r * 1.05, cx + r * 1.45, cy + r * 0.95), fill=(0, 0, 0, 0)
        )
        image.alpha_composite(moon)
        spread = min(r, w / 2 / 4.2)  # keep the stars on narrow strips
        for dx, dy, s in ((-2.6, -0.5, 9), (2.4, 0.4, 7), (3.4, -0.9, 5), (-3.6, 0.7, 5)):
            _star(draw, cx + dx * spread, cy + dy * r, s * SS, (246, 234, 186, 255))
    return image


def _star(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, fill: RGBA) -> None:
    points = []
    for i in range(8):
        angle = math.pi / 4 * i - math.pi / 2
        radius = size if i % 2 == 0 else size * 0.32
        points.append((x + math.cos(angle) * radius, y + math.sin(angle) * radius))
    draw.polygon(points, fill=fill)


def draw_celebration_gold(template: PhotoTemplate) -> Image.Image:
    w, h = template.width_px * SS, template.height_px * SS
    image = _vertical_gradient((w, h), (34, 25, 19, 255), (22, 16, 12, 255))
    gold, light_gold = (212, 160, 23, 255), (245, 215, 122, 255)
    rng = random.Random(f"gold/{template.key}")  # noqa: S311 - repeatable art, not security
    confetti = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    colours = ((212, 160, 23), (245, 230, 200), (232, 160, 180), (245, 215, 122))
    count = template.width_px * template.height_px // 4200
    for _ in range(count):
        x, y = rng.uniform(0, template.width_px), rng.uniform(0, template.height_px)
        if not _in_margin(template, x, y, 10):
            continue
        colour = (*rng.choice(colours), rng.randint(170, 255))
        piece = Image.new("RGBA", (16 * SS, 16 * SS), (0, 0, 0, 0))
        pdraw = ImageDraw.Draw(piece)
        if rng.random() < 0.5:
            pdraw.rectangle((5 * SS, 2 * SS, 10 * SS, 13 * SS), fill=colour)
        else:
            pdraw.ellipse((4 * SS, 4 * SS, 11 * SS, 11 * SS), fill=colour)
        piece = piece.rotate(rng.uniform(0, 180), resample=Image.Resampling.BICUBIC)
        confetti.alpha_composite(piece, (round((x - 8) * SS), round((y - 8) * SS)))
    image.alpha_composite(confetti)
    draw = ImageDraw.Draw(image)
    for inset, colour, width in ((10, gold, 3), (17, light_gold, 1)):
        i = inset * SS
        draw.rectangle((i, i, w - i - 1, h - i - 1), outline=colour, width=width * SS)
    for slot in template.slots:
        draw.rectangle(_scaled(slot.rect, 6), outline=gold, width=3 * SS)
        draw.rectangle(_scaled(slot.rect, 2), outline=light_gold, width=SS)
    top, bottom = _footer_band(template)
    band = bottom - top
    if band >= 80:
        cx, cy = w / 2, (top + bottom) / 2 * SS
        size = min(band * 0.16, 44) * SS
        for dx, scale in ((-3.2, 0.6), (0, 1.0), (3.2, 0.6)):
            x, s = cx + dx * size, size * scale
            draw.polygon(
                ((x, cy - s), (x + s * 0.7, cy), (x, cy + s), (x - s * 0.7, cy)), fill=light_gold
            )
        reach = min(size * 9, w / 2 - 40 * SS)  # inside the gold border on narrow strips
        draw.line((cx - reach, cy, cx - size * 4.4, cy), fill=gold, width=2 * SS)
        draw.line((cx + size * 4.4, cy, cx + reach, cy), fill=gold, width=2 * SS)
    return image


DRAWERS: dict[str, Callable[[PhotoTemplate], Image.Image]] = {
    "minimal_light": draw_minimal_light,
    "midnight": draw_midnight,
    "celebration_gold": draw_celebration_gold,
}


def render(family_id: str, template: PhotoTemplate) -> Image.Image:
    big = DRAWERS[family_id](template)
    image = big.resize((template.width_px, template.height_px), Image.Resampling.LANCZOS)
    clear = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    for slot in template.slots:
        r = slot.rect
        image.paste(clear.resize((r.w, r.h)), (r.x, r.y))
    return image


def main(out: Path = BUILTIN_DIRECTORY) -> int:
    templates = {t.key: t for t in JsonTemplateRepository().latest()}
    out.mkdir(parents=True, exist_ok=True)
    validator = PillowFrameValidator()
    for frame in builtin_frames():
        template = templates[frame.template_key]
        if template.version != BUILTIN_TEMPLATE_VERSION:
            raise SystemExit(f"{template.key} is version {template.version}; update the catalogue")
        path = out / frame.filename
        render(frame.family.id, template).save(path, format="PNG", optimize=True)
        report = validator.validate(path.read_bytes(), template)
        print(f"{frame.filename}: {path.stat().st_size} bytes, slots {report.slot_transparency}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
