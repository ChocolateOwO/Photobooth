"""Participant-facing shapes for a booth session. Nothing from the admin side is described here:
no profile name, no asset ids, no storage keys, no file paths, no frame provenance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from photobooth.modules.sessions.domain import (
    BoothSession,
    CaptureOutcome,
    DeliveryLink,
    OutputAsset,
    ShotProgress,
)

IdempotencyKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")]
FrameId = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


class StartSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: IdempotencyKey = Field(
        description="Repeat the same key to retry safely; it never starts a second visit."
    )


class StartTestBody(StartSessionBody):
    """The organizer names the saved profile to try; it is read, never activated or changed."""

    profile_id: FrameId


class ChooseFrameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: FrameId


class RetakeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_index: int | None = Field(
        default=None, ge=1, le=64, description="Which photo to take again; all of them when null."
    )
    state_version: int | None = Field(
        default=None,
        ge=1,
        description="The version of the visit this answers; a later one refuses the retake.",
    )


class RenderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: IdempotencyKey = Field(
        description="Repeat the same key to retry safely; the photos are made once."
    )


class OutputResponse(BaseModel):
    """One finished photo (a print, or one strip of a 2x6)."""

    id: str
    output_index: int
    width: int
    height: int
    version: str = Field(description="Changes when the photo does.")

    @classmethod
    def of(cls, output: OutputAsset) -> OutputResponse:
        return cls(
            id=output.id,
            output_index=output.output_index,
            width=output.width,
            height=output.height,
            version=(output.sha256 or "")[:16],
        )


class DeliveryLinkResponse(BaseModel):
    """The take-home link. Shown on the booth screen only; it is the guest's key to the photos."""

    url: str
    expires_at: datetime
    qr_svg: str = Field(description="The link as a QR code (SVG, dark on light).")

    @classmethod
    def of(cls, link: DeliveryLink) -> DeliveryLinkResponse:
        return cls(url=link.url, expires_at=link.expires_at, qr_svg=link.qr_svg)


class ShotResponse(BaseModel):
    shot_index: int
    attempt_no: int
    done: bool
    capture_id: str | None = Field(
        default=None, description="The photo that counts for this shot; null while it is missing."
    )
    version: str | None = Field(default=None, description="Changes when the photo does.")

    @classmethod
    def of(cls, shot: ShotProgress) -> ShotResponse:
        return cls(
            shot_index=shot.shot_index,
            attempt_no=shot.attempt_no,
            done=shot.done,
            capture_id=shot.capture_id,
            version=shot.version,
        )


class BoothSessionResponse(BaseModel):
    """The session as the booth screens see it."""

    id: str
    is_test: bool = Field(description="An organizer trying the booth from Admin, not a guest.")
    state: str
    state_version: int
    countdown_seconds: int
    mirror: bool
    retake_mode: str
    inactivity_timeout_s: int
    expected_captures: int
    taken: int
    template_key: str | None
    layout_label: str | None
    frame_id: str | None
    shots: list[ShotResponse]
    outputs: list[OutputResponse] = Field(
        default_factory=list, description="The finished photos, once they are made."
    )

    @classmethod
    def of(
        cls,
        session: BoothSession,
        shots: list[ShotProgress] | None = None,
        outputs: list[OutputAsset] | None = None,
    ) -> BoothSessionResponse:
        selection = session.selection
        return cls(
            id=session.id,
            is_test=session.is_test,
            state=str(session.state),
            state_version=session.state_version,
            countdown_seconds=session.countdown_seconds,
            mirror=session.mirror,
            retake_mode=str(session.retake_mode),
            inactivity_timeout_s=session.profile.inactivity_timeout_s,
            expected_captures=session.expected_capture_count,
            taken=session.successful_capture_count,
            template_key=selection.template_key if selection else None,
            layout_label=selection.layout_label if selection else None,
            frame_id=selection.frame_id if selection else None,
            shots=[ShotResponse.of(shot) for shot in shots or []],
            outputs=[OutputResponse.of(output) for output in outputs or []],
        )


class CaptureResponse(BaseModel):
    capture_id: str
    shot_index: int
    attempt_no: int
    status: str
    session: BoothSessionResponse

    @classmethod
    def of(cls, outcome: CaptureOutcome, shots: list[ShotProgress]) -> CaptureResponse:
        return cls(
            capture_id=outcome.capture.id,
            shot_index=outcome.capture.shot_index,
            attempt_no=outcome.capture.attempt_no,
            status=str(outcome.capture.status),
            session=BoothSessionResponse.of(outcome.session, shots),
        )
