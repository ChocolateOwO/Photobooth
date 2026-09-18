"""Frame domain: frame asset entity, validation report and ports (no framework imports)."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from photobooth.modules.templates.domain import PhotoTemplate

NAME_MAX_LENGTH = 80
NAME_PATTERN = re.compile(r"^[^\x00-\x1f]+$")


class FrameStatus(StrEnum):
    VALID = "valid"


class FrameError(Exception):
    """Base error for frame operations."""


class FrameValidationError(FrameError):
    """The uploaded file can not be used as a frame for this template."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = list(problems)


class FrameNotFoundError(FrameError):
    def __init__(self, frame_id: str) -> None:
        super().__init__(f"frame not found: {frame_id}")


class FrameInUseError(FrameError):
    """The frame is still selected by an Event Profile, so it can not be deleted."""

    def __init__(self, profile_names: Sequence[str]) -> None:
        names = ", ".join(profile_names)
        super().__init__(
            "this frame is still used by: "
            f"{names}. Select another frame there (or replace this file) first"
        )
        self.profile_names = list(profile_names)


class FrameReadOnlyError(FrameError):
    """Built-in frames ship with the app and can not be replaced, renamed or deleted."""

    def __init__(self) -> None:
        super().__init__(
            "Built-in frames can not be changed or deleted. Upload your own frame to use a "
            "different design."
        )


@dataclass(frozen=True)
class FrameValidationReport:
    """Warnings are recorded with the frame; problems are raised as FrameValidationError."""

    warnings: tuple[str, ...] = ()
    width: int = 0
    height: int = 0
    slot_transparency: tuple[float, ...] = ()


@dataclass(frozen=True)
class FrameAsset:
    id: str
    media_asset_id: str
    template_key: str
    template_version: int
    name: str
    status: FrameStatus
    report: FrameValidationReport
    created_at: datetime
    updated_at: datetime
    # Copied from the stored media asset for the API/UI; bytes always come from storage.
    sha256: str = ""
    bytes: int = 0
    # Packaged with the app (read-only); `family` groups the matching frames of all layouts.
    builtin: bool = False
    family: str | None = None


def check_frame_name(name: str) -> str:
    """Frames are named by the admin; the client file name is never used or stored."""
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > NAME_MAX_LENGTH:
        raise FrameValidationError([f"The frame name must be 1-{NAME_MAX_LENGTH} characters."])
    if NAME_PATTERN.fullmatch(cleaned) is None:
        raise FrameValidationError(["The frame name must not contain control characters."])
    return cleaned


class FrameValidator(Protocol):
    """Checks untrusted PNG bytes against a template. Raises FrameValidationError."""

    def validate(self, data: bytes, template: PhotoTemplate) -> FrameValidationReport: ...


class FrameRepository(ABC):
    @abstractmethod
    def add(self, frame: FrameAsset) -> FrameAsset: ...

    @abstractmethod
    def list_frames(self, template_key: str | None = None) -> list[FrameAsset]: ...

    @abstractmethod
    def get(self, frame_id: str) -> FrameAsset | None: ...

    @abstractmethod
    def replace_file(
        self,
        frame_id: str,
        media_asset_id: str,
        report: FrameValidationReport,
        at: datetime,
    ) -> FrameAsset:
        """Point an existing frame at newly uploaded bytes; profile selections stay valid."""

    @abstractmethod
    def rename(self, frame_id: str, name: str, at: datetime) -> FrameAsset: ...

    @abstractmethod
    def delete(self, frame_id: str) -> None:
        """Raise FrameInUseError when an Event Profile still selects this frame."""

    @abstractmethod
    def uses_asset(self, asset_id: str, ignore_frame_id: str | None = None) -> bool:
        """Whether any frame (other than `ignore_frame_id`) still points at this stored file."""


class StoredAsset(Protocol):
    """What the frames module needs from a stored media asset."""

    @property
    def id(self) -> str: ...

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    @property
    def bytes(self) -> int: ...

    @property
    def sha256(self) -> str: ...


class AssetUsage(Protocol):
    def is_referenced(self, asset_id: str) -> bool: ...


class AssetStore(Protocol):
    """Content-addressed storage of the original bytes (assets module)."""

    def upload(self, kind: str, data: bytes) -> StoredAsset: ...

    def content(self, asset_id: str) -> tuple[StoredAsset, bytes]: ...

    def discard_if_unused(self, asset_id: str, usage: AssetUsage) -> bool: ...

    def ensure_stored(self, asset_id: str, data: bytes) -> bool:
        """Write these exact bytes for an existing asset row when storage lacks them."""
        ...
