"""Local filesystem StorageProvider confined to the instance storage root."""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path

from photobooth.modules.storage.domain import (
    InvalidStorageKeyError,
    StorageError,
    StorageKey,
    StorageProvider,
)


class LocalStorageProvider(StorageProvider):
    """Maps validated keys under `root`. Every resolved path (after symlink/junction resolution)
    must stay inside the root, so a junction planted inside storage can not redirect writes."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self._root = Path(os.path.realpath(root))

    def _path(self, key: StorageKey) -> Path:
        candidate = self._root.joinpath(*key.segments)
        real = Path(os.path.realpath(candidate))
        if real != self._root and self._root not in real.parents:
            raise InvalidStorageKeyError(f"storage key escapes the storage root: {key}")
        return candidate

    def put(self, key: StorageKey, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path(key)  # re-check after creating parents (a parent could be a junction)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(data).digest():
                raise StorageError(f"refusing to overwrite different content at {key}")
            return
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        try:
            with open(tmp, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def get(self, key: StorageKey) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(f"missing blob: {key}") from exc

    def exists(self, key: StorageKey) -> bool:
        return self._path(key).is_file()

    def delete(self, key: StorageKey) -> None:
        self._path(key).unlink(missing_ok=True)
