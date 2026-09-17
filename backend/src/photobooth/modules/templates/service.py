"""Template registry and specification use cases."""

from __future__ import annotations

from photobooth.modules.templates.domain import PhotoTemplate, TemplateArtist, TemplateRepository


class TemplateSpecService:
    """Single source for spec data, blank PNG and guide PNG, all read from the same definition."""

    def __init__(self, repository: TemplateRepository, artist: TemplateArtist) -> None:
        self._repository = repository
        self._artist = artist
        self._cache: dict[tuple[str, int, str], bytes] = {}

    def list_latest(self) -> list[PhotoTemplate]:
        return self._repository.latest()

    def get(self, key: str, version: int | None = None) -> PhotoTemplate:
        return self._repository.get(key, version)

    def blank_png(self, key: str, version: int | None = None) -> bytes:
        return self._image(self.get(key, version), "blank")

    def guide_png(self, key: str, version: int | None = None) -> bytes:
        return self._image(self.get(key, version), "guide")

    def _image(self, template: PhotoTemplate, kind: str) -> bytes:
        cache_key = (template.key, template.version, kind)
        if cache_key not in self._cache:
            draw = self._artist.blank_png if kind == "blank" else self._artist.guide_png
            self._cache[cache_key] = draw(template)
        return self._cache[cache_key]
