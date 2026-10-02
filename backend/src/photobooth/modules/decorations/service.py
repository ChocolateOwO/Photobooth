"""Decoration use cases: what the booth may offer, and checking what a guest chose."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from photobooth.modules.decorations.domain import (
    FILTERS,
    NO_FILTER,
    FilterPreset,
    PlacedSticker,
    Sticker,
    StickerLibrary,
    filter_preset,
    parse_spec,
    read_canonical,
)


@dataclass(frozen=True)
class Catalog:
    filters: tuple[FilterPreset, ...]
    stickers: tuple[Sticker, ...]


@dataclass(frozen=True)
class StickerArt:
    """A placed sticker together with its PNG, ready to be pasted."""

    png: bytes
    placed: PlacedSticker


@dataclass(frozen=True)
class OutputDecoration:
    """Everything one finished photo needs: the filter matrix (None: no filter) and stickers."""

    matrix: tuple[float, ...] | None
    stickers: tuple[StickerArt, ...]


class DecorationService:
    def __init__(self, library: StickerLibrary) -> None:
        self._library = library

    def catalog(self) -> Catalog:
        return Catalog(filters=FILTERS, stickers=tuple(self._library.stickers()))

    def sticker_png(self, key: str) -> bytes:
        """Raises DecorationError for a sticker that is not offered."""
        return self._library.png(key)

    def prepare(self, raw: object, outputs: int) -> str | None:
        """Check a guest's decoration and return the text it is stored as (None: no decoration,
        so an undecorated visit is made exactly as before). Raises DecorationError."""
        if raw is None:
            return None
        spec = parse_spec(raw, outputs, self._keys())
        return None if spec.empty else spec.canonical()

    def for_output(self, canonical: str | None, output_index: int) -> OutputDecoration:
        """What the renderer applies to one finished photo of a stored decoration."""
        if canonical is None:
            return OutputDecoration(matrix=None, stickers=())
        spec = read_canonical(canonical)
        return OutputDecoration(
            matrix=None if spec.filter == NO_FILTER else filter_preset(spec.filter).matrix,
            stickers=tuple(
                StickerArt(png=self._library.png(placed.sticker), placed=placed)
                for placed in spec.on(output_index)
            ),
        )

    def _keys(self) -> Sequence[str]:
        return [sticker.key for sticker in self._library.stickers()]
