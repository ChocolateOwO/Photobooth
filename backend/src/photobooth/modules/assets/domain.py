"""Asset domain: media asset entity, validation limits and ports (no framework imports)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class AssetKind(StrEnum):
    LOGO = "logo"
    BACKGROUND = "background"
    FRAME = "frame"  # uploaded through the frames module, which validates it against a template


class AssetValidationError(Exception):
    """Plain-language reason an upload was refused."""


class AssetNotFoundError(LookupError):
    def __init__(self, asset_id: str) -> None:
        super().__init__(f"asset not found: {asset_id}")


@dataclass(frozen=True)
class UploadLimits:
    max_bytes: int
    max_width: int
    max_height: int
    min_width: int = 16
    min_height: int = 16


LIMITS: dict[AssetKind, UploadLimits] = {
    AssetKind.LOGO: UploadLimits(max_bytes=5 * 1024 * 1024, max_width=4096, max_height=4096),
    AssetKind.BACKGROUND: UploadLimits(max_bytes=12 * 1024 * 1024, max_width=7680, max_height=7680),
    # Frame rules (plan): PNG, exact canvas size, at most 10 MB.
    AssetKind.FRAME: UploadLimits(max_bytes=10 * 1024 * 1024, max_width=7680, max_height=7680),
}

ALLOWED_FORMATS: dict[str, tuple[str, str]] = {  # detected format -> (mime, extension)
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
}


@dataclass(frozen=True)
class ImageFacts:
    format: str
    width: int
    height: int
    has_alpha: bool
    animated: bool


@dataclass(frozen=True)
class MediaAsset:
    id: str
    kind: AssetKind
    storage_key: str
    mime: str
    width: int
    height: int
    bytes: int
    sha256: str
    created_at: datetime


class ImageInspector(Protocol):
    """Decodes untrusted bytes safely and reports facts; raises AssetValidationError."""

    def inspect(self, data: bytes, limits: UploadLimits) -> ImageFacts: ...


class AssetRepository(ABC):
    @abstractmethod
    def add(self, asset: MediaAsset) -> MediaAsset:
        """Insert; if (kind, sha256) already exists return the existing row instead."""

    @abstractmethod
    def get(self, asset_id: str) -> MediaAsset | None: ...

    @abstractmethod
    def find_by_hash(self, kind: AssetKind, sha256: str) -> MediaAsset | None: ...
