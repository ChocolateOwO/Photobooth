"""Decorations: the filters and stickers a guest may add to the finished photos.

A decoration is a small description (which filter, which stickers where), never a change to a
file: the original photos and the organizer's frame stay exactly as they were, and the server
applies the description only while it makes the finished photos.

Geometry is relative to one finished photo (one print, or one strip of a 2x6), so the booth's
preview at any screen size and the server's 300-DPI render place a sticker identically:
- `x`, `y`: the sticker's centre, as fractions of the photo's width and height (0..1);
- `size`: the sticker's width as a fraction of the photo's width (its height follows the
  sticker's own proportions);
- `rotation`: degrees clockwise, -180 < rotation <= 180.
Stickers lie on top of the frame, in the order they were added.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

SPEC_VERSION = 1
MAX_STICKERS_PER_OUTPUT = 12
MIN_SIZE = 0.05
MAX_SIZE = 1.0
# Decimal places kept for every number, so equal decorations always read (and hash) the same.
PRECISION = 4


class DecorationError(ValueError):
    """The decoration can not be used (unknown filter or sticker, out of range, too many)."""


@dataclass(frozen=True)
class FilterPreset:
    """A colour filter: an affine colour matrix on 0..1 sRGB values.

    `matrix` has three rows (red, green, blue out) of four numbers: the weights of red, green and
    blue in, and an offset. The booth applies it with an SVG feColorMatrix in sRGB; the server
    applies the very same numbers with Pillow. Both clamp to 0..1.
    """

    key: str
    label: str
    matrix: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.matrix) != 12:
            raise ValueError("a filter matrix has 3 rows of 4 numbers")


def _contrast(gain: float, lift: float) -> tuple[float, ...]:
    offset = (1 - gain) * 0.5 + lift
    return (gain, 0, 0, offset, 0, gain, 0, offset, 0, 0, gain, offset)


_LUMA = (0.299, 0.587, 0.114)

# PROVISIONAL filter set (PLAN product defaults): none, mono, sepia, warm, cool, bright.
FILTERS: tuple[FilterPreset, ...] = (
    FilterPreset("none", "Original", (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)),
    FilterPreset("mono", "Black & white", (*_LUMA, 0, *_LUMA, 0, *_LUMA, 0)),
    FilterPreset(
        "sepia",
        "Sepia",
        (0.393, 0.769, 0.189, 0, 0.349, 0.686, 0.168, 0, 0.272, 0.534, 0.131, 0),
    ),
    FilterPreset("warm", "Warm", (1.08, 0, 0, 0.02, 0, 1.0, 0, 0.01, 0, 0, 0.86, 0)),
    FilterPreset("cool", "Cool", (0.9, 0, 0, 0, 0, 1.0, 0, 0.01, 0, 0, 1.1, 0.03)),
    FilterPreset("bright", "Bright", _contrast(1.12, 0.05)),
)
FILTER_KEYS = tuple(preset.key for preset in FILTERS)
NO_FILTER = "none"


def filter_preset(key: str) -> FilterPreset:
    for preset in FILTERS:
        if preset.key == key:
            return preset
    raise DecorationError(f"unknown filter {key!r}")


@dataclass(frozen=True)
class Sticker:
    """A sticker the booth offers: an sRGB PNG with transparency."""

    key: str
    label: str
    width: int
    height: int
    version: str


@dataclass(frozen=True)
class PlacedSticker:
    sticker: str
    output: int
    x: float
    y: float
    size: float
    rotation: float


@dataclass(frozen=True)
class DecorationSpec:
    filter: str
    stickers: tuple[PlacedSticker, ...]

    @property
    def empty(self) -> bool:
        return self.filter == NO_FILTER and not self.stickers

    def on(self, output_index: int) -> tuple[PlacedSticker, ...]:
        return tuple(s for s in self.stickers if s.output == output_index)

    def canonical(self) -> str:
        """The one text this decoration is stored and compared as."""
        return json.dumps(
            {
                "version": SPEC_VERSION,
                "filter": self.filter,
                "stickers": [
                    {
                        "sticker": s.sticker,
                        "output": s.output,
                        "x": s.x,
                        "y": s.y,
                        "size": s.size,
                        "rotation": s.rotation,
                    }
                    for s in self.stickers
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def _number(raw: object, name: str, low: float, high: float) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise DecorationError(f"{name} must be a number")
    value = float(raw)
    if not math.isfinite(value) or not low <= value <= high:
        raise DecorationError(f"{name} must be between {low:g} and {high:g}")
    return round(value, PRECISION) + 0.0  # -0.0 reads as 0.0


def _rotation(raw: object) -> float:
    value = _number(raw, "rotation", -3600, 3600)
    turned = math.remainder(value, 360.0)  # -180 <= turned <= 180
    if turned == -180.0:
        turned = 180.0
    return round(turned, PRECISION) + 0.0


def parse_spec(raw: object, outputs: int, stickers: Sequence[str]) -> DecorationSpec:
    """Check a decoration from the booth against this visit: its outputs and the offered stickers.

    Accepts the booth's JSON shape: {"filter": key, "stickers": [{sticker, output, x, y, size,
    rotation}, ...]}. Unknown fields are refused, so nothing unexpected is ever stored.
    """
    if not isinstance(raw, Mapping):
        raise DecorationError("a decoration is an object")
    extra = set(raw) - {"version", "filter", "stickers"}
    if extra:
        raise DecorationError(f"unknown decoration fields: {', '.join(sorted(map(str, extra)))}")
    version = raw.get("version", SPEC_VERSION)
    if version != SPEC_VERSION:
        raise DecorationError(f"decoration version must be {SPEC_VERSION}")
    key = raw.get("filter", NO_FILTER)
    if not isinstance(key, str):
        raise DecorationError("filter must be a name")
    filter_preset(key)
    placed_raw = raw.get("stickers", [])
    if not isinstance(placed_raw, list):
        raise DecorationError("stickers must be a list")
    offered = set(stickers)
    placed: list[PlacedSticker] = []
    for item in placed_raw:
        if not isinstance(item, Mapping):
            raise DecorationError("each sticker is an object")
        fields = {"sticker", "output", "x", "y", "size", "rotation"}
        if set(item) != fields:
            raise DecorationError(f"each sticker has exactly: {', '.join(sorted(fields))}")
        name = item["sticker"]
        if not isinstance(name, str) or name not in offered:
            raise DecorationError("unknown sticker")
        output = item["output"]
        if isinstance(output, bool) or not isinstance(output, int) or not 1 <= output <= outputs:
            raise DecorationError(f"output must be 1..{outputs}")
        placed.append(
            PlacedSticker(
                sticker=name,
                output=output,
                x=_number(item["x"], "x", 0.0, 1.0),
                y=_number(item["y"], "y", 0.0, 1.0),
                size=_number(item["size"], "size", MIN_SIZE, MAX_SIZE),
                rotation=_rotation(item["rotation"]),
            )
        )
    for output in range(1, outputs + 1):
        if sum(1 for s in placed if s.output == output) > MAX_STICKERS_PER_OUTPUT:
            raise DecorationError(f"at most {MAX_STICKERS_PER_OUTPUT} stickers on one photo")
    return DecorationSpec(filter=key, stickers=tuple(placed))


def read_canonical(text: str) -> DecorationSpec:
    """A stored decoration (already checked when it was stored)."""
    raw = json.loads(text)
    return DecorationSpec(
        filter=raw["filter"],
        stickers=tuple(
            PlacedSticker(
                sticker=s["sticker"],
                output=s["output"],
                x=s["x"],
                y=s["y"],
                size=s["size"],
                rotation=s["rotation"],
            )
            for s in raw["stickers"]
        ),
    )


class StickerLibrary(Protocol):
    """Where the offered stickers and their PNG files come from."""

    def stickers(self) -> Sequence[Sticker]: ...

    def png(self, key: str) -> bytes:
        """Raises DecorationError for a sticker that is not offered."""
        ...
