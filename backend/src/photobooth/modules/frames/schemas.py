"""Frame API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

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
    builtin: bool = Field(description="Packaged with the app; can not be replaced or deleted")
    family: str | None = Field(description="Built-in family id, e.g. midnight; null for uploads")
    used_by: list[str] = Field(
        default_factory=list, description="Event Profiles offering this frame to participants"
    )

    @classmethod
    def of(cls, frame: FrameAsset, used_by: list[str] | None = None) -> FrameResponse:
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
            builtin=frame.builtin,
            family=frame.family,
            used_by=list(used_by or []),
        )


class RenameFrameBody(BaseModel):
    name: str
