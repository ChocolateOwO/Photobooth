"""Asset use cases: validate, store content-addressed, look up."""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from photobooth.modules.assets.domain import (
    ALLOWED_FORMATS,
    LIMITS,
    AssetKind,
    AssetNotFoundError,
    AssetRepository,
    AssetUsage,
    AssetValidationError,
    ImageInspector,
    MediaAsset,
)
from photobooth.modules.storage.domain import StorageError, StorageKey, StorageProvider


def _now() -> datetime:
    return datetime.now(UTC)


class AssetService:
    def __init__(
        self,
        repository: AssetRepository,
        storage: StorageProvider,
        inspector: ImageInspector,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._inspector = inspector
        self._clock = clock
        self._new_id = new_id

    def upload(self, kind: str, data: bytes) -> MediaAsset:
        """Validate and store an image. The client's file name and path are never used."""
        try:
            asset_kind = AssetKind(kind)
        except ValueError as exc:
            raise AssetValidationError("Asset kind must be 'logo' or 'background'.") from exc
        facts = self._inspector.inspect(data, LIMITS[asset_kind])
        mime, extension = ALLOWED_FORMATS[facts.format]
        digest = hashlib.sha256(data).hexdigest()
        existing = self._repository.find_by_hash(asset_kind, digest)
        if existing is not None:
            return existing
        key = StorageKey(f"assets/{asset_kind.value}/{digest[:2]}/{digest}.{extension}")
        self._storage.put(key, data)
        return self._repository.add(
            MediaAsset(
                id=self._new_id(),
                kind=asset_kind,
                storage_key=key.value,
                mime=mime,
                width=facts.width,
                height=facts.height,
                bytes=len(data),
                sha256=digest,
                created_at=self._clock(),
            )
        )

    def discard_if_unused(self, asset_id: str, usage: AssetUsage) -> bool:
        """Remove a stored image (row and file) when nothing references it any more.

        Used after a frame is deleted and after a failed frame upload. Assets shared by another
        frame or Event Profile are kept, and a missing file is not an error.
        """
        asset = self._repository.get(asset_id)
        if asset is None:
            return False
        if usage.is_referenced(asset_id):
            return False
        self._repository.remove(asset_id)
        with contextlib.suppress(StorageError):  # deleting a missing blob is fine
            self._storage.delete(StorageKey(asset.storage_key))
        return True

    def ensure_stored(self, asset_id: str, data: bytes) -> bool:
        """Put the packaged bytes of an existing asset row into storage when they are missing.

        Used for built-in frames: their rows come from a migration, their files ship with the app.
        The bytes must match the recorded sha256, so nothing else can be written this way.
        """
        asset = self.get(asset_id)
        if hashlib.sha256(data).hexdigest() != asset.sha256:
            raise AssetValidationError(f"packaged content does not match asset {asset_id}")
        key = StorageKey(asset.storage_key)
        if self._storage.exists(key):
            return False
        self._storage.put(key, data)
        return True

    def get(self, asset_id: str) -> MediaAsset:
        asset = self._repository.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        return asset

    def exists(self, asset_id: str, kind: str) -> bool:
        asset = self._repository.get(asset_id)
        return asset is not None and asset.kind.value == kind

    def content(self, asset_id: str) -> tuple[MediaAsset, bytes]:
        asset = self.get(asset_id)
        try:
            return asset, self._storage.get(StorageKey(asset.storage_key))
        except StorageError as exc:  # metadata without content: treat as missing, never leak paths
            raise AssetNotFoundError(asset_id) from exc
