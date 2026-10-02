"""Built-in sticker library: sRGB PNGs with transparency packaged with the app (read-only).

The PNGs live in `photobooth/stickers_data/builtin/<key>.png`. They were drawn offline by
`scripts/assets/make_builtin_stickers.py`. The booth shows these exact files while a guest
decorates, and the server pastes the same files into the finished photos.
"""

from __future__ import annotations

import functools
import hashlib
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from photobooth.modules.decorations.domain import DecorationError, Sticker, StickerLibrary

BUILTIN_DIRECTORY = Path(__file__).resolve().parents[2] / "stickers_data" / "builtin"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class BuiltinSticker:
    key: str
    label: str

    @property
    def filename(self) -> str:
        return f"{self.key}.png"


BUILTIN_STICKERS: tuple[BuiltinSticker, ...] = (
    BuiltinSticker("heart", "Heart"),
    BuiltinSticker("star", "Star"),
    BuiltinSticker("sparkles", "Sparkles"),
    BuiltinSticker("crown", "Crown"),
    BuiltinSticker("sunglasses", "Sunglasses"),
    BuiltinSticker("party_hat", "Party hat"),
    BuiltinSticker("wow", "Wow!"),
    BuiltinSticker("lips", "Kiss"),
    BuiltinSticker("mustache", "Mustache"),
    BuiltinSticker("balloon", "Balloon"),
    BuiltinSticker("flower", "Flower"),
    BuiltinSticker("smiley", "Smiley"),
)


def _png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != _PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise DecorationError("a sticker file is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


class PackagedStickerLibrary(StickerLibrary):
    """The stickers shipped with the app, read once and kept in memory (they are small)."""

    def __init__(self, directory: Path = BUILTIN_DIRECTORY) -> None:
        self._directory = directory

    @functools.cached_property
    def _files(self) -> dict[str, tuple[Sticker, bytes]]:
        files: dict[str, tuple[Sticker, bytes]] = {}
        for item in BUILTIN_STICKERS:
            data = (self._directory / item.filename).read_bytes()
            width, height = _png_size(data)
            files[item.key] = (
                Sticker(
                    key=item.key,
                    label=item.label,
                    width=width,
                    height=height,
                    version=hashlib.sha256(data).hexdigest()[:16],
                ),
                data,
            )
        return files

    def stickers(self) -> Sequence[Sticker]:
        return [sticker for sticker, _data in self._files.values()]

    def png(self, key: str) -> bytes:
        found = self._files.get(key)
        if found is None:
            raise DecorationError("unknown sticker")
        return found[1]
