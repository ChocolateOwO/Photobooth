"""Asset API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from photobooth.modules.assets.domain import AssetKind, MediaAsset


class MediaAssetResponse(BaseModel):
    """Stored asset metadata. The storage key and client file name are never exposed."""

    id: str
    kind: AssetKind
    mime: str
    width: int
    height: int
    bytes: int
    sha256: str
    created_at: datetime

    @classmethod
    def of(cls, asset: MediaAsset) -> MediaAssetResponse:
        return cls(
            id=asset.id,
            kind=asset.kind,
            mime=asset.mime,
            width=asset.width,
            height=asset.height,
            bytes=asset.bytes,
            sha256=asset.sha256,
            created_at=asset.created_at,
        )
