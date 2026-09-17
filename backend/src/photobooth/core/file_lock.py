"""Blocking cross-process file lock for short critical sections (e.g. ledger read-modify-write)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import TracebackType
from typing import IO

LOCK_OFFSET = 0x10000


class FileLockTimeoutError(TimeoutError):
    """The lock was not acquired within the timeout."""


class ExclusiveFileLock:
    """Exclusive OS lock on one byte of `path`, retried until `timeout_seconds`."""

    def __init__(
        self, path: Path, timeout_seconds: float = 30.0, poll_seconds: float = 0.05
    ) -> None:
        self._path = path
        self._timeout = timeout_seconds
        self._poll = poll_seconds
        self._handle: IO[bytes] | None = None

    def __enter__(self) -> ExclusiveFileLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+b")
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                _lock(handle)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise FileLockTimeoutError(f"could not lock {self._path}") from None
                time.sleep(self._poll)
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None


def _lock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(LOCK_OFFSET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(LOCK_OFFSET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
