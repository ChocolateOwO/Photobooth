"""Pillow palette extraction: dominant colours of a background image, locally and offline.

Reads only; the stored image is never modified. Only the PNG and JPEG decoders see the bytes (the
same formats the assets module accepts), and the image is reduced to a thumbnail before counting.
"""

from __future__ import annotations

import io
import warnings

from PIL import Image

from photobooth.modules.themes.domain import PaletteColor, ThemeSourceError

THUMBNAIL = (160, 160)
QUANTIZE_COLORS = 10
MERGE_DISTANCE = 20  # Euclidean RGB distance under which two swatches count as one colour
MIN_SHARE = 0.01


class PillowPaletteExtractor:
    def extract(self, data: bytes) -> list[PaletteColor]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data), formats=("PNG", "JPEG")) as image:
                    image.draft("RGB", (THUMBNAIL[0] * 2, THUMBNAIL[1] * 2))
                    image.thumbnail(THUMBNAIL)
                    rgba = image.convert("RGBA")
        except (
            OSError,
            ValueError,
            SyntaxError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise ThemeSourceError("The background image could not be read.") from exc

        # Fully transparent pixels of a PNG background carry no colour.
        opaque = Image.new("RGB", rgba.size)
        opaque.paste(rgba.convert("RGB"), mask=rgba.getchannel("A"))
        mask = rgba.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
        quantized = opaque.quantize(colors=QUANTIZE_COLORS, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette() or []
        counts: dict[int, int] = {}
        for index, visible in zip(quantized.getdata(), mask.getdata(), strict=True):
            if visible:
                counts[index] = counts.get(index, 0) + 1
        total = sum(counts.values())
        if total == 0:
            raise ThemeSourceError("The background image has no visible pixels.")

        merged: list[list[float]] = []  # r, g, b, count
        for index, count in sorted(counts.items(), key=lambda item: -item[1]):
            r, g, b = palette[index * 3 : index * 3 + 3]
            for entry in merged:
                if (
                    (entry[0] - r) ** 2 + (entry[1] - g) ** 2 + (entry[2] - b) ** 2
                ) ** 0.5 < MERGE_DISTANCE:
                    weight = entry[3] + count
                    entry[0] = (entry[0] * entry[3] + r * count) / weight
                    entry[1] = (entry[1] * entry[3] + g * count) / weight
                    entry[2] = (entry[2] * entry[3] + b * count) / weight
                    entry[3] = weight
                    break
            else:
                merged.append([r, g, b, count])
        colors = [
            PaletteColor((round(e[0]), round(e[1]), round(e[2])), e[3] / total) for e in merged
        ]
        kept = [c for c in colors if c.share >= MIN_SHARE]
        return sorted(kept or colors[:1], key=lambda c: -c.share)
