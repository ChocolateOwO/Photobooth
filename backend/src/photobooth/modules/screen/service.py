"""TV screen services: the PC camera the TV booth photographs with, and TV pairing codes."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from photobooth.core.kiosk_pairing import DeviceCredentialRegistry
from photobooth.modules.screen.domain import (
    TV_CODE_DIGITS,
    TV_CODE_MAX_TRIES,
    TV_CODE_TTL_SECONDS,
    CameraChoiceStore,
    PcCameraInfo,
    PcCameras,
)

Clock = Callable[[], float]


class PcCameraService:
    """The camera an organizer chose in Admin for the TV booth."""

    def __init__(self, cameras: PcCameras, choice: CameraChoiceStore) -> None:
        self._cameras = cameras
        self._choice = choice

    def cameras(self) -> list[PcCameraInfo]:
        return self._cameras.available()

    def chosen(self) -> int | None:
        return self._choice.load()

    def choose(self, index: int | None) -> None:
        self._choice.save(index)

    def frame(self, max_width: int | None = None) -> bytes:
        index = self._choice.load()
        if index is None:
            index = 0  # until an organizer chooses: the PC's first camera, like a browser does
        return self._cameras.frame(index, max_width)

    def preview(self, index: int, max_width: int | None = None) -> bytes:
        return self._cameras.frame(index, max_width)

    def close(self) -> None:
        self._cameras.close()


@dataclass(frozen=True)
class _PendingTvCode:
    code: str
    expires_at: float
    tries_left: int


class TvPairingService:
    """Short codes an organizer reads off Admin and types on the TV, once.

    Six digits are easy to type with a TV remote. A code lives two minutes, a new one replaces the
    old one, and five wrong tries end it, so guessing is not a way in.
    """

    def __init__(
        self, credentials: DeviceCredentialRegistry, clock: Clock = time.monotonic
    ) -> None:
        self._credentials = credentials
        self._clock = clock
        self._pending: _PendingTvCode | None = None
        self._lock = threading.Lock()

    def new_code(self) -> tuple[str, int]:
        code = str(secrets.randbelow(10**TV_CODE_DIGITS)).zfill(TV_CODE_DIGITS)
        with self._lock:
            self._pending = _PendingTvCode(
                code, self._clock() + TV_CODE_TTL_SECONDS, TV_CODE_MAX_TRIES
            )
        return code, int(TV_CODE_TTL_SECONDS)

    def consume(self, code: str | None) -> tuple[str, str] | None:
        """New (cookie_token, device_key) when `code` is the current code, else None."""
        typed = (code or "").strip()
        with self._lock:
            pending = self._pending
            if pending is None:
                return None
            if self._clock() > pending.expires_at:
                self._pending = None
                return None
            if not hmac.compare_digest(typed.encode(), pending.code.encode()):
                left = pending.tries_left - 1
                self._pending = (
                    None if left <= 0 else _PendingTvCode(pending.code, pending.expires_at, left)
                )
                return None
            self._pending = None
        return self._credentials.issue()
