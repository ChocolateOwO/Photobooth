"""Booth decoration shapes (participant-safe: no files or storage)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from photobooth.modules.decorations.domain import MAX_STICKERS_PER_OUTPUT, FilterPreset, Sticker
from photobooth.modules.decorations.service import Catalog


class FilterResponse(BaseModel):
    key: str = Field(examples=["sepia"])
    label: str = Field(examples=["Sepia"])
    matrix: list[float] = Field(
        description=(
            "Three rows (red, green, blue out) of four numbers: red, green and blue in, then an "
            "offset, on 0..1 sRGB values. The booth previews exactly what the server applies."
        ),
        min_length=12,
        max_length=12,
    )

    @classmethod
    def of(cls, preset: FilterPreset) -> FilterResponse:
        return cls(key=preset.key, label=preset.label, matrix=list(preset.matrix))


class StickerResponse(BaseModel):
    key: str = Field(examples=["heart"])
    label: str = Field(examples=["Heart"])
    url: str
    width: int
    height: int

    @classmethod
    def of(cls, sticker: Sticker) -> StickerResponse:
        return cls(
            key=sticker.key,
            label=sticker.label,
            url=f"/api/booth/decorations/stickers/{sticker.key}.png?v={sticker.version}",
            width=sticker.width,
            height=sticker.height,
        )


class DecorationCatalogResponse(BaseModel):
    filters: list[FilterResponse]
    stickers: list[StickerResponse]
    max_stickers_per_photo: int

    @classmethod
    def of(cls, catalog: Catalog) -> DecorationCatalogResponse:
        return cls(
            filters=[FilterResponse.of(preset) for preset in catalog.filters],
            stickers=[StickerResponse.of(sticker) for sticker in catalog.stickers],
            max_stickers_per_photo=MAX_STICKERS_PER_OUTPUT,
        )
