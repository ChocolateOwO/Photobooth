"""Theme use cases: the preset catalogue and theme extraction from a profile background."""

from __future__ import annotations

from typing import Protocol

from photobooth.modules.themes.domain import (
    DEFAULT_PRESET,
    PRESET_LIST,
    EventTheme,
    PaletteColor,
    Preset,
    theme_from_palette,
)


class BackgroundImages(Protocol):
    """Original bytes of an uploaded background (assets module). Raises ThemeSourceError."""

    def background_bytes(self, asset_id: str) -> bytes: ...


class PaletteExtractor(Protocol):
    def extract(self, data: bytes) -> list[PaletteColor]: ...


class ThemeService:
    def __init__(self, backgrounds: BackgroundImages, extractor: PaletteExtractor) -> None:
        self._backgrounds = backgrounds
        self._extractor = extractor

    def presets(self) -> tuple[Preset, ...]:
        return PRESET_LIST

    def default_preset(self) -> str:
        return DEFAULT_PRESET

    def extract(self, background_asset_id: str) -> EventTheme:
        """A complete accessible theme from the background's dominant colours (never modifies
        the image; runs offline)."""
        data = self._backgrounds.background_bytes(background_asset_id)
        return theme_from_palette(self._extractor.extract(data))
