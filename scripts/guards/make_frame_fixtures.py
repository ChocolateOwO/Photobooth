"""Generate e2e frame fixtures: one valid frame per approved template plus invalid examples.

Frames are normally drawn outside the app; these files only exercise the validator and the UI.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from photobooth.modules.templates.repository import JsonTemplateRepository


def valid_frame(template: object, colour: tuple[int, int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (template.width_px, template.height_px), colour)  # type: ignore[attr-defined]
    for slot in template.slots:  # type: ignore[attr-defined]
        rect = slot.rect
        image.paste((0, 0, 0, 0), (rect.x, rect.y, rect.x + rect.w, rect.y + rect.h))
    return image


def main(directory: str) -> int:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    templates = {t.key: t for t in JsonTemplateRepository().latest()}
    colours = {
        "strip_2x6": (20, 40, 90, 255),
        "print_3x4": (90, 20, 40, 255),
        "print_4x6": (20, 90, 40, 255),
    }
    for key, template in templates.items():
        valid_frame(template, colours.get(key, (30, 30, 30, 255))).save(out / f"frame_{key}.png")
        # A second, visibly different file for the replace flow.
        valid_frame(template, (200, 200, 20, 255)).save(out / f"frame_{key}_v2.png")

    strip = templates["strip_2x6"]
    # Wrong size for every template.
    Image.new("RGBA", (321, 456), (10, 10, 10, 255)).save(out / "frame_wrong_size.png")
    # Right size, but the photo areas are painted over.
    Image.new("RGBA", (strip.width_px, strip.height_px), (10, 10, 10, 255)).save(
        out / "frame_opaque_slots.png"
    )
    # Not a PNG at all.
    Image.new("RGB", (strip.width_px, strip.height_px), (10, 10, 10)).save(
        out / "frame_not_png.jpg", quality=80
    )
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
