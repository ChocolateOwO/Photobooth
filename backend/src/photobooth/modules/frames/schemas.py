"""Frame API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from photobooth.modules.frames.domain import FrameAsset


class FrameResponse(BaseModel):
    """A validated frame. The stored file itself is served by `/content`."""

    id: str
    template_key: str
    template_version: int
    name: str
    status: str
    width: int
    height: int
    bytes: int
    sha256: str
    warnings: list[str]
    slot_transparency: list[float]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, frame: FrameAsset) -> FrameResponse:
        return cls(
            id=frame.id,
            template_key=frame.template_key,
            template_version=frame.template_version,
            name=frame.name,
            status=frame.status.value,
            width=frame.report.width,
            height=frame.report.height,
            bytes=frame.bytes,
            sha256=frame.sha256,
            warnings=list(frame.report.warnings),
            slot_transparency=[round(value, 4) for value in frame.report.slot_transparency],
            created_at=frame.created_at,
            updated_at=frame.updated_at,
        )


class RenameFrameBody(BaseModel):
    name: str
