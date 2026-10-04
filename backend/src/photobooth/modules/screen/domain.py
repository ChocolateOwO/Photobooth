"""TV screen: the booth on a TV's browser, photographing with this PC's camera.

Ports only; the OpenCV camera and the file that remembers the chosen camera are infrastructure
wired by the composition root.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

TV_CODE_DIGITS = 6
TV_CODE_TTL_SECONDS = 120.0
TV_CODE_MAX_TRIES = 5


class CameraUnavailableError(Exception):
    """No picture: no camera chosen, the camera is missing, or another program holds it."""


@dataclass(frozen=True)
class PcCameraInfo:
    index: int
    label: str


@dataclass(frozen=True)
class TvAddress:
    """The address a TV opens to pair (None when the TV screen listener is off)."""

    url: str | None


class PcCameras(Protocol):
    """This PC's cameras, by index."""

    def available(self) -> list[PcCameraInfo]: ...

    def frame(self, index: int, max_width: int | None) -> bytes:
        """The newest picture of camera `index` as JPEG. Raises CameraUnavailableError."""
        ...

    def close(self) -> None: ...


class CameraChoiceStore(Protocol):
    def load(self) -> int | None: ...

    def save(self, index: int | None) -> None: ...
