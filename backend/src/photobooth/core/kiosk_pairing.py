"""Kiosk device credential groundwork.

Loopback is not an identity: any local process can reach 127.0.0.1. The booth browser
therefore proves itself with a device cookie obtained by consuming a one-time pairing
code that only the booth user can read from `<instance>\\config\\runtime\\pairing.code`.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

PAIRING_CODE_FILENAME = "pairing.code"
LAUNCHER_TOKEN_FILENAME = "launcher.token"  # noqa: S105 - a file name, not a secret
LAUNCHER_HEADER = "X-Photobooth-Launcher"
PAIRING_CODE_TTL_SECONDS = 60.0
ROTATE_MIN_INTERVAL_SECONDS = 1.0

Clock = Callable[[], float]


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


class PairingCodeStore(Protocol):
    """Where the current pairing code is published for the trusted launcher."""

    def publish(self, code: str) -> None: ...

    def clear(self) -> None: ...


class RuntimeSecretFile:
    """A secret published atomically to `runtime_dir/<filename>` (UTF-8, no newline).

    The runtime directory is readable only by the booth user once the containment gate applies ACLs.
    """

    def __init__(self, runtime_dir: Path, filename: str) -> None:
        self._dir = runtime_dir
        self._filename = filename
        self.path = runtime_dir / filename

    def publish(self, value: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._dir / f".{self._filename}.{secrets.token_hex(4)}.tmp"
        tmp.write_text(value, encoding="utf-8")
        os.replace(tmp, self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class FilePairingCodeStore(RuntimeSecretFile):
    """The pairing code file read by the trusted launcher."""

    def __init__(self, runtime_dir: Path) -> None:
        super().__init__(runtime_dir, PAIRING_CODE_FILENAME)


class LauncherCredential:
    """Per-process secret that authorizes pairing-code rotation (launcher only).

    Rotation is a mutation and loopback + Host are not an identity: the caller proves it can read
    the runtime directory by presenting this token in the `X-Photobooth-Launcher` header.
    """

    def __init__(self, store: RuntimeSecretFile) -> None:
        self._store = store
        self._token = secrets.token_urlsafe(32)
        self._digest = _digest(self._token)
        store.publish(self._token)

    @property
    def path(self) -> Path:
        return self._store.path

    def verify(self, token: str | None) -> bool:
        if not token:
            return False
        return hmac.compare_digest(_digest(token), self._digest)

    def clear(self) -> None:
        self._store.clear()


class DeviceCredentialRegistry:
    """In-memory, hashed device credentials. A new registry per process = rotation on restart.

    Pairing issues TWO independent secrets:
    - the device cookie (HttpOnly). Cookies are shared by every port of 127.0.0.1, so any local
      server the kiosk browser visits receives it; it only proves "some paired browser".
    - the device key, delivered once in the pairing redirect URL fragment (never sent to any
      server) and kept in the UI origin storage. It is not derivable from the cookie and no
      endpoint returns it, so a captured cookie can not be replayed as a mutation.
    """

    def __init__(self) -> None:
        self._keys_by_token: dict[bytes, bytes] = {}
        self._lock = threading.Lock()

    def issue(self) -> tuple[str, str]:
        """Return (cookie_token, device_key) for a newly paired device."""
        token = secrets.token_urlsafe(32)
        key = secrets.token_urlsafe(32)
        with self._lock:
            self._keys_by_token[_digest(token)] = _digest(key)
        return token, key

    def _key_digest(self, token: str | None) -> bytes | None:
        if not token:
            return None
        candidate = _digest(token)
        with self._lock:
            for known, key_digest in self._keys_by_token.items():
                if hmac.compare_digest(candidate, known):
                    return key_digest
        return None

    def verify(self, token: str | None) -> bool:
        return self._key_digest(token) is not None

    def verify_key(self, token: str | None, key: str | None) -> bool:
        """True only for the key issued together with this cookie token."""
        key_digest = self._key_digest(token)
        if key_digest is None or not key:
            return False
        return hmac.compare_digest(_digest(key), key_digest)


@dataclass(frozen=True)
class _PendingCode:
    digest: bytes
    expires_at: float


class PairingService:
    """Issues single-use, short-lived pairing codes and exchanges them for device credentials."""

    def __init__(
        self,
        store: PairingCodeStore,
        credentials: DeviceCredentialRegistry,
        clock: Clock = time.monotonic,
        ttl_seconds: float = PAIRING_CODE_TTL_SECONDS,
    ) -> None:
        self._store = store
        self._credentials = credentials
        self._clock = clock
        self._ttl = ttl_seconds
        self._pending: _PendingCode | None = None
        self._last_rotation: float | None = None
        self._lock = threading.Lock()

    def rotate(self) -> bool:
        """Publish a fresh code, invalidating any previous one. False when rate limited.

        The code itself is never returned; only the runtime file carries it.
        """
        with self._lock:
            now = self._clock()
            if (
                self._last_rotation is not None
                and now - self._last_rotation < ROTATE_MIN_INTERVAL_SECONDS
            ):
                return False
            code = secrets.token_urlsafe(32)
            self._pending = _PendingCode(digest=_digest(code), expires_at=now + self._ttl)
            self._last_rotation = now
            self._store.publish(code)
        return True

    def consume(self, code: str | None) -> tuple[str, str] | None:
        """Return new (cookie_token, device_key) if `code` is the current unexpired code."""
        if not code:
            return None
        with self._lock:
            pending = self._pending
            if pending is None:
                return None
            valid = hmac.compare_digest(_digest(code), pending.digest)
            if not valid:
                return None
            self._pending = None
            self._store.clear()
            if self._clock() > pending.expires_at:
                return None
        return self._credentials.issue()

    def shutdown(self) -> None:
        with self._lock:
            self._pending = None
            self._store.clear()
