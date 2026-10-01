"""QR code rendering (segno): an SVG the booth screen can show at any size."""

from __future__ import annotations

import io

import segno


class SegnoQrEncoder:
    """Dark modules on a light square with the standard 4-module quiet zone, so any phone camera
    reads it whatever the event's colours are. Error correction M survives a smudged screen.

    A standalone SVG document (with its namespace): the booth shows it as an image, and an image
    without the SVG namespace is not an SVG to a browser at all.
    """

    def svg(self, text: str) -> str:
        code = segno.make(text, error="m", micro=False)
        out = io.BytesIO()
        code.save(
            out,
            kind="svg",
            scale=1,
            border=4,
            dark="#000000",
            light="#ffffff",
            omitsize=True,
            svgclass="qr",
            title="QR code",
            xmldecl=False,
            svgns=True,
            nl=False,
        )
        return out.getvalue().decode("utf-8")
