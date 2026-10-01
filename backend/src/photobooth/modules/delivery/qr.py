"""QR code rendering (segno): an SVG the booth screen can show at any size."""

from __future__ import annotations

import segno


class SegnoQrEncoder:
    """Dark modules on a light square with the standard 4-module quiet zone, so any phone camera
    reads it whatever the event's colours are. Error correction M survives a smudged screen."""

    def svg(self, text: str) -> str:
        code = segno.make(text, error="m", micro=False)
        rendered: str = code.svg_inline(
            scale=1,
            border=4,
            dark="#000000",
            light="#ffffff",
            omitsize=True,
            svgclass="qr",
            title="QR code",
        )
        return rendered
