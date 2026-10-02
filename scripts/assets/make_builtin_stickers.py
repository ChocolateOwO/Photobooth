"""Draw the packaged built-in sticker PNGs (offline, deterministic).

Run from the repository root with the backend virtualenv:
    backend\\.venv\\Scripts\\python.exe scripts\\assets\\make_builtin_stickers.py

Each sticker is drawn at twice the size and reduced for smooth edges, given a white die-cut
outline, trimmed to its own outline and saved as an sRGB PNG with transparency. The booth shows
these exact files while the guest decorates, and the server pastes the same files into the
finished photos.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from photobooth.modules.decorations.builtin import BUILTIN_DIRECTORY, BUILTIN_STICKERS

SS = 2  # supersampling factor
SIDE = 512 * SS
OUTLINE = 14 * SS
RGBA = tuple[int, int, int, int]
Drawing = Callable[[ImageDraw.ImageDraw], None]

INK = (40, 32, 38, 255)
GOLD = (250, 192, 40, 255)
GOLD_DARK = (205, 140, 20, 255)
RED = (232, 52, 76, 255)
PINK = (250, 120, 170, 255)
BLUE = (60, 140, 240, 255)
YELLOW = (255, 214, 60, 255)
WHITE = (255, 255, 255, 255)


def _star_points(cx: float, cy: float, outer: float, inner: float, points: int, turn: float = 0):
    result = []
    for i in range(points * 2):
        radius = outer if i % 2 == 0 else inner
        angle = math.pi * i / points - math.pi / 2 + turn
        result.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return result


def _heart(draw: ImageDraw.ImageDraw) -> None:
    c, s = SIDE / 2, SIDE * 0.42
    points = []
    for i in range(360):
        t = math.radians(i)
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        points.append((c + x * s / 16, c - y * s / 16 + s * 0.08))
    draw.polygon(points, fill=RED)
    draw.ellipse((c - s * 0.62, c - s * 0.55, c - s * 0.32, c - s * 0.3), fill=(255, 150, 160, 255))


def _star(draw: ImageDraw.ImageDraw) -> None:
    c = SIDE / 2
    draw.polygon(_star_points(c, c + SIDE * 0.03, SIDE * 0.46, SIDE * 0.2, 5), fill=GOLD)
    draw.polygon(
        _star_points(c, c + SIDE * 0.03, SIDE * 0.3, SIDE * 0.13, 5), fill=(255, 220, 90, 255)
    )


def _sparkles(draw: ImageDraw.ImageDraw) -> None:
    for cx, cy, r in ((0.42, 0.55, 0.36), (0.78, 0.24, 0.17), (0.8, 0.78, 0.13)):
        draw.polygon(
            _star_points(SIDE * cx, SIDE * cy, SIDE * r, SIDE * r * 0.22, 4),
            fill=(255, 236, 120, 255),
        )


def _crown(draw: ImageDraw.ImageDraw) -> None:
    w, h = SIDE, SIDE
    base_top, base_bottom = h * 0.62, h * 0.8
    spikes = [
        (w * 0.1, base_top),
        (w * 0.08, h * 0.28),
        (w * 0.3, h * 0.46),
        (w * 0.5, h * 0.2),
        (w * 0.7, h * 0.46),
        (w * 0.92, h * 0.28),
        (w * 0.9, base_top),
    ]
    draw.polygon(spikes, fill=GOLD)
    draw.rounded_rectangle(
        (w * 0.08, base_top - 4, w * 0.92, base_bottom), radius=20, fill=GOLD_DARK
    )
    for x, y in ((0.08, 0.28), (0.5, 0.2), (0.92, 0.28)):
        r = w * 0.05
        draw.ellipse((w * x - r, h * y - r, w * x + r, h * y + r), fill=WHITE)
    for x, color in ((0.28, RED), (0.5, BLUE), (0.72, (60, 190, 120, 255))):
        r = w * 0.045
        cy = (base_top + base_bottom) / 2
        draw.ellipse((w * x - r, cy - r, w * x + r, cy + r), fill=color)


def _sunglasses(draw: ImageDraw.ImageDraw) -> None:
    w, h = SIDE, SIDE
    top = h * 0.36
    draw.rounded_rectangle((w * 0.04, top, w * 0.46, top + h * 0.26), radius=60, fill=INK)
    draw.rounded_rectangle((w * 0.54, top, w * 0.96, top + h * 0.26), radius=60, fill=INK)
    draw.rectangle((w * 0.44, top + 20, w * 0.56, top + 56), fill=INK)
    draw.rectangle((w * 0.02, top, w * 0.98, top + 40), fill=INK)
    for x in (0.1, 0.6):
        draw.line(
            (w * x, top + h * 0.08, w * (x + 0.12), top + h * 0.2),
            fill=(120, 120, 140, 255),
            width=18,
        )


def _party_hat(draw: ImageDraw.ImageDraw) -> None:
    w, h = SIDE, SIDE
    apex, left, right = (w * 0.5, h * 0.12), (w * 0.2, h * 0.86), (w * 0.8, h * 0.86)
    draw.polygon((apex, left, right), fill=(140, 90, 230, 255))
    for i, t in enumerate((0.3, 0.52, 0.74)):
        y = apex[1] + (left[1] - apex[1]) * t
        half = (right[0] - left[0]) / 2 * t
        draw.polygon(
            (
                (w * 0.5 - half, y),
                (w * 0.5 + half, y),
                (w * 0.5 + half * 1.12, y + h * 0.07),
                (w * 0.5 - half * 1.12, y + h * 0.07),
            ),
            fill=(YELLOW, PINK, (90, 210, 220, 255))[i],
        )
    r = w * 0.08
    draw.ellipse((apex[0] - r, apex[1] - r, apex[0] + r, apex[1] + r), fill=PINK)


def _wow(draw: ImageDraw.ImageDraw) -> None:
    w, h = SIDE, SIDE
    draw.ellipse((w * 0.04, h * 0.14, w * 0.96, h * 0.74), fill=WHITE, outline=INK, width=22)
    draw.polygon(((w * 0.26, h * 0.64), (w * 0.14, h * 0.92), (w * 0.44, h * 0.7)), fill=WHITE)
    draw.line(
        ((w * 0.26, h * 0.67), (w * 0.14, h * 0.92), (w * 0.44, h * 0.71)), fill=INK, width=22
    )
    font = ImageFont.load_default(size=round(h * 0.24))
    text = "WOW!"
    box = draw.textbbox((0, 0), text, font=font, stroke_width=6)
    draw.text(
        (w / 2 - (box[2] - box[0]) / 2 - box[0], h * 0.44 - (box[3] - box[1]) / 2 - box[1]),
        text,
        font=font,
        fill=RED,
        stroke_width=6,
        stroke_fill=RED,
    )


def _lips(draw: ImageDraw.ImageDraw) -> None:
    w, h = SIDE, SIDE
    cy = h * 0.5
    upper = []
    lower = []
    for i in range(101):
        t = i / 100
        x = w * (0.06 + 0.88 * t)
        bow = math.sin(math.pi * t)
        dip = math.exp(-(((t - 0.5) / 0.08) ** 2)) * 0.07
        upper.append((x, cy - h * (0.2 * bow**0.7 - dip)))
        lower.append((x, cy + h * 0.2 * bow**0.8))
    draw.polygon(upper + lower[::-1], fill=RED)
    draw.line(
        [(x, cy + h * 0.015 * math.sin(math.pi * i / 100)) for i, (x, _) in enumerate(upper)],
        fill=(150, 20, 40, 255),
        width=12,
    )
    draw.ellipse((w * 0.56, cy + h * 0.06, w * 0.7, cy + h * 0.12), fill=(255, 140, 150, 255))


def _mustache(draw: ImageDraw.ImageDraw) -> None:
    w, h = SIDE, SIDE
    color = (70, 44, 30, 255)
    cy = h * 0.5
    for side in (-1, 1):
        points = []
        for i in range(61):
            t = i / 60
            x = w / 2 + side * w * 0.46 * t
            top = cy - h * 0.14 * math.sin(math.pi * min(1.0, t * 1.15)) + h * 0.02
            curl = h * 0.1 * max(0.0, (t - 0.75) / 0.25) ** 2
            points.append((x, top - curl))
        for i in range(60, -1, -1):
            t = i / 60
            x = w / 2 + side * w * 0.46 * t
            bottom = (
                cy
                + h * 0.1 * math.sin(math.pi * t) ** 0.6
                - h * 0.12 * max(0.0, (t - 0.8) / 0.2) ** 2
            )
            points.append((x, bottom))
        draw.polygon(points, fill=color)


def _balloon(draw: ImageDraw.ImageDraw) -> None:
    w, h = SIDE, SIDE
    draw.line(
        [(w * 0.5 + w * 0.04 * math.sin(i / 6), h * (0.72 + 0.26 * i / 40)) for i in range(41)],
        fill=INK,
        width=10,
    )
    draw.ellipse((w * 0.22, h * 0.04, w * 0.78, h * 0.72), fill=BLUE)
    draw.polygon(((w * 0.46, h * 0.76), (w * 0.54, h * 0.76), (w * 0.5, h * 0.7)), fill=BLUE)
    draw.ellipse((w * 0.32, h * 0.14, w * 0.42, h * 0.3), fill=(170, 210, 255, 255))


def _flower(draw: ImageDraw.ImageDraw) -> None:
    c, r = SIDE / 2, SIDE * 0.2
    for i in range(6):
        angle = math.tau * i / 6
        x, y = c + math.cos(angle) * r * 1.15, c + math.sin(angle) * r * 1.15
        draw.ellipse((x - r, y - r, x + r, y + r), fill=PINK)
    draw.ellipse((c - r * 0.8, c - r * 0.8, c + r * 0.8, c + r * 0.8), fill=YELLOW)


def _smiley(draw: ImageDraw.ImageDraw) -> None:
    w, h = SIDE, SIDE
    draw.ellipse((w * 0.06, h * 0.06, w * 0.94, h * 0.94), fill=YELLOW)
    for x in (0.36, 0.64):
        draw.ellipse((w * x - 30, h * 0.34, w * x + 30, h * 0.48), fill=INK)
    draw.arc((w * 0.26, h * 0.3, w * 0.74, h * 0.76), start=25, end=155, fill=INK, width=30)
    for x in (0.24, 0.76):
        draw.ellipse((w * x - 44, h * 0.56, w * x + 44, h * 0.64), fill=(255, 150, 120, 200))


DRAWINGS: dict[str, Drawing] = {
    "heart": _heart,
    "star": _star,
    "sparkles": _sparkles,
    "crown": _crown,
    "sunglasses": _sunglasses,
    "party_hat": _party_hat,
    "wow": _wow,
    "lips": _lips,
    "mustache": _mustache,
    "balloon": _balloon,
    "flower": _flower,
    "smiley": _smiley,
}


def _die_cut(art: Image.Image) -> Image.Image:
    """A white outline around the drawing, as on a printed sticker."""
    alpha = art.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    grown = alpha
    step = 9  # MaxFilter sizes must be odd; grow in passes for a round outline
    for _ in range(OUTLINE // (step // 2)):
        grown = grown.filter(ImageFilter.MaxFilter(step))
    grown = grown.filter(ImageFilter.GaussianBlur(1.5 * SS))
    outline = Image.new("RGBA", art.size, WHITE)
    outline.putalpha(grown)
    return Image.alpha_composite(outline, art)


def draw_sticker(key: str) -> Image.Image:
    pad = OUTLINE * 2
    art = Image.new("RGBA", (SIDE + pad * 2, SIDE + pad * 2), (0, 0, 0, 0))
    layer = Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 0))
    DRAWINGS[key](ImageDraw.Draw(layer))
    art.paste(layer, (pad, pad))
    cut = _die_cut(art)
    box = cut.getchannel("A").getbbox()
    assert box is not None
    trimmed = cut.crop(box)
    return trimmed.resize(
        (max(1, trimmed.width // SS), max(1, trimmed.height // SS)), Image.Resampling.LANCZOS
    )


def main() -> int:
    BUILTIN_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for sticker in BUILTIN_STICKERS:
        image = draw_sticker(sticker.key)
        image.save(BUILTIN_DIRECTORY / sticker.filename, format="PNG", optimize=True)
        print(f"{sticker.filename}: {image.width}x{image.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
