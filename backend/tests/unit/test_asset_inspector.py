"""Untrusted image validation for logo/background uploads."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image

from photobooth.modules.assets.domain import LIMITS, AssetKind, AssetValidationError, UploadLimits
from photobooth.modules.assets.inspector import PillowImageInspector

LOGO = LIMITS[AssetKind.LOGO]


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (64, 48), mode: str = "RGBA") -> bytes:
    buffer = io.BytesIO()
    colors: dict[str, int | tuple[int, ...]] = {"RGBA": (10, 20, 30, 128), "RGB": (10, 20, 30)}
    Image.new(mode, size, colors.get(mode, 1000)).save(buffer, fmt)
    return buffer.getvalue()


def _png_header_only(width: int, height: int) -> bytes:
    """A syntactically valid PNG signature + IHDR claiming huge dimensions (no pixel data)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def test_accepts_png_and_jpeg() -> None:
    inspector = PillowImageInspector()
    png = inspector.inspect(image_bytes("PNG"), LOGO)
    assert (png.format, png.width, png.height, png.has_alpha) == ("PNG", 64, 48, True)
    jpeg = inspector.inspect(image_bytes("JPEG", mode="RGB"), LOGO)
    assert (jpeg.format, jpeg.has_alpha) == ("JPEG", False)


def _gif_animated() -> bytes:
    buffer = io.BytesIO()
    frames = [Image.new("P", (32, 32), i) for i in range(2)]
    frames[0].save(buffer, "GIF", save_all=True, append_images=frames[1:])
    return buffer.getvalue()


def _apng() -> bytes:
    buffer = io.BytesIO()
    frames = [Image.new("RGBA", (32, 32), (i * 100, 0, 0, 255)) for i in range(2)]
    frames[0].save(buffer, "PNG", save_all=True, append_images=frames[1:])
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"not an image at all", "not a valid"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "not a valid"),
        (image_bytes("GIF", mode="RGB"), "not a valid"),
        (image_bytes("BMP", mode="RGB"), "not a valid"),
        (image_bytes("WEBP", mode="RGB"), "not a valid"),
        (_gif_animated(), "not a valid"),
        (_apng(), "Animated"),
        (image_bytes("PNG")[:60], "not a valid"),  # truncated
        (image_bytes("PNG", size=(8, 8)), "too small"),
        (image_bytes("PNG", size=(4097, 20)), "too large"),
        (_png_header_only(5000, 5000), "too large"),  # header beyond the limit, no pixel data
        (_png_header_only(60000, 60000), "not a valid"),  # Pillow's bomb guard fires at open
        (image_bytes("PNG", mode="I;16"), "color mode"),
    ],
)
def test_rejects_invalid_uploads(data: bytes, message: str) -> None:
    with pytest.raises(AssetValidationError, match=message):
        PillowImageInspector().inspect(data, LOGO)


def test_rejects_oversized_bytes_before_decoding() -> None:
    tiny = UploadLimits(max_bytes=100, max_width=4096, max_height=4096)
    with pytest.raises(AssetValidationError, match="too large"):
        PillowImageInspector().inspect(image_bytes("PNG", size=(256, 256)), tiny)


def test_bomb_within_dimension_limit_is_still_refused() -> None:
    generous = UploadLimits(max_bytes=10_000, max_width=200_000, max_height=200_000)
    with pytest.raises(AssetValidationError):
        PillowImageInspector().inspect(_png_header_only(100_000, 100_000), generous)


def test_presentation_copy_keeps_palette_transparency_and_drops_text() -> None:
    from PIL.PngImagePlugin import PngInfo

    from photobooth.modules.assets.inspector import presentation_copy

    image = Image.new("P", (20, 10), 0)
    image.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    image.paste(1, (5, 0, 10, 10))
    info = PngInfo()
    info.add_text("Author", "Private Person")
    buffer = io.BytesIO()
    image.save(buffer, "PNG", transparency=0, pnginfo=info)
    data, mime = presentation_copy(buffer.getvalue())
    assert mime == "image/png" and b"Private" not in data
    with Image.open(io.BytesIO(data)) as copy:
        rgba = copy.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0
        assert rgba.getpixel((6, 5)) == (255, 0, 0, 255)
