"""Participant-facing shapes for a booth session. Nothing from the admin side is described here:
no profile name, no asset ids, no storage keys, no file paths, no frame provenance.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from photobooth.modules.sessions.domain import (
    BoothSession,
    CaptureOutcome,
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


class ChooseFrameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: FrameId


class RetakeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_index: int | None = Field(
        default=None, ge=1, le=64, description="Which photo to take again; all of them when null."
    )


class ShotResponse(BaseModel):
    shot_index: int
    attempt_no: int
    done: bool

    @classmethod
    def of(cls, shot: ShotProgress) -> ShotResponse:
        return cls(shot_index=shot.shot_index, attempt_no=shot.attempt_no, done=shot.done)


class BoothSessionResponse(BaseModel):
    """The session as the booth screens see it."""

    id: str
    state: str
    state_version: int
    countdown_seconds: int
    mirror: bool
    retake_mode: str
    expected_captures: int
    taken: int
    template_key: str | None
    layout_label: str | None
    frame_id: str | None
    shots: list[ShotResponse]

    @classmethod
    def of(
        cls, session: BoothSession, shots: list[ShotProgress] | None = None
    ) -> BoothSessionResponse:
        selection = session.selection
        return cls(
            id=session.id,
            state=str(session.state),
            state_version=session.state_version,
            countdown_seconds=session.countdown_seconds,
            mirror=session.mirror,
            retake_mode=str(session.retake_mode),
            expected_captures=session.expected_capture_count,
            taken=session.successful_capture_count,
            template_key=selection.template_key if selection else None,
            layout_label=selection.layout_label if selection else None,
            frame_id=selection.frame_id if selection else None,
            shots=[ShotResponse.of(shot) for shot in shots or []],
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
