"""Storage domain: validated storage keys and the provider port. Clients never supply paths."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


class StorageError(Exception):
    """A storage operation failed or was refused."""


class InvalidStorageKeyError(StorageError):
    """The key is not a safe, relative, server-generated key."""


_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,99}(\.[a-z0-9]{1,8})?$")


@dataclass(frozen=True)
class StorageKey:
    """Lower-case, forward-slash separated, relative key such as `assets/logo/ab/abcd.png`.

    Rejects empty segments, `.`/`..`, backslashes, drive letters, absolute paths, dots at the start
    of a segment and anything outside `[a-z0-9_-.]`, so a key can never express a path traversal.
    """

    value: str

    def __post_init__(self) -> None:
        value = self.value
        if not value or len(value) > 255:
            raise InvalidStorageKeyError("storage key must be 1..255 characters")
        segments = value.split("/")
        if len(segments) > 8 or any(not _SEGMENT.fullmatch(segment) for segment in segments):
            raise InvalidStorageKeyError(f"unsafe storage key: {value!r}")

    @property
    def segments(self) -> tuple[str, ...]:
        return tuple(self.value.split("/"))

    def __str__(self) -> str:
        return self.value


class StorageProvider(ABC):
    """Stores immutable blobs by key."""

    @abstractmethod
    def put(self, key: StorageKey, data: bytes) -> None:
        """Write atomically. Existing identical content is kept; different content is refused."""

    @abstractmethod
    def get(self, key: StorageKey) -> bytes:
        """Raise StorageError when missing."""

    @abstractmethod
    def exists(self, key: StorageKey) -> bool: ...

    @abstractmethod
    def size(self, key: StorageKey) -> int:
        """The stored size in bytes; 0 for a blob that is not there."""

    @abstractmethod
    def delete(self, key: StorageKey) -> None:
        """Idempotent: deleting a missing key succeeds."""
