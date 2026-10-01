"""Booth session domain: one participant's visit, its state machine and its captures.

The server is authoritative. A client proposes a step (choose a frame, send a photo, retake, give
up); this module decides whether the step is allowed, and every decision is made from the session's
own snapshot, never from the live Event Profile. An organizer editing the profile mid-session
therefore changes nothing for the participant already at the booth.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

# A session may not be fed more than this per shot, however often a photo is retaken.
MAX_ATTEMPTS_PER_SHOT = 5
# Captures are JPEG frames from the booth camera; the body cap leaves room for multipart framing.
MAX_CAPTURE_BYTES = 12 * 1024 * 1024
MIN_CAPTURE_SIDE = 240
MAX_CAPTURE_SIDE = 8000


class SessionError(Exception):
    """Base error for booth sessions."""


class NoActiveEventError(SessionError):
    def __init__(self) -> None:
        super().__init__("no event is active on this booth yet")


class SessionNotFoundError(SessionError):
    def __init__(self) -> None:
        super().__init__("this booth session no longer exists")


class SessionClosedError(SessionError):
    """The session ended (given up, timed out or failed); nothing may be added to it."""

    def __init__(self, state: str) -> None:
        super().__init__(f"this booth session is {state}")
        self.state = state


class StaleSessionError(SessionError):
    """Someone else moved the session on; the client must read it again."""

    def __init__(self) -> None:
        super().__init__("this booth session moved on; read it again")


class TransitionRefusedError(SessionError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class FrameNotOfferedError(SessionError):
    def __init__(self, frame_id: str) -> None:
        super().__init__(f"frame {frame_id} is not offered by this session's event")


class StaleAttemptError(SessionError):
    """A photo from an attempt that a retake already replaced."""

    def __init__(self, shot_index: int, expected: int) -> None:
        super().__init__(f"photo {shot_index} is now on attempt {expected}")
        self.shot_index = shot_index
        self.expected = expected


class IdempotencyReuseError(SessionError):
    def __init__(self) -> None:
        super().__init__("this idempotency key was used for a different request")


class OperationFailedError(SessionError):
    """The recorded outcome of this key was a failure; the client uses a new key."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CaptureRefusedError(SessionError):
    """The photo itself is not usable (not a JPEG, too small, too large)."""


class CaptureNotFoundError(SessionError):
    def __init__(self) -> None:
        super().__init__("that photo is not part of this booth session")


class TooManyCapturesError(SessionError):
    def __init__(self, shot_index: int) -> None:
        super().__init__(f"photo {shot_index} has been retaken too many times")


class EligibilityRefusedError(SessionError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RenderBusyError(SessionError):
    """The render worker is full; nothing was recorded, so the same request may be retried."""

    def __init__(self) -> None:
        super().__init__("the booth is busy making photos; try again in a moment")


class RenderFailedError(SessionError):
    """The finished photos could not be made from this visit's photos and frame."""

    def __init__(self, code: str) -> None:
        super().__init__("the photos could not be made")
        self.code = code


class OutputNotFoundError(SessionError):
    def __init__(self) -> None:
        super().__init__("that finished photo is not part of this booth session")


class SessionState(StrEnum):
    STARTED = "started"
    ELIGIBILITY_OK = "eligibility_ok"
    CAPTURING = "capturing"
    REVIEWING = "reviewing"
    # The finished photos exist and the guest can take them home (QR link).
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"
    ABANDONED = "abandoned"


TERMINAL_STATES: frozenset[SessionState] = frozenset(
    {SessionState.COMPLETED, SessionState.CANCELLED, SessionState.ERROR, SessionState.ABANDONED}
)

# Every step a session may take.
ALLOWED_TRANSITIONS: Mapping[SessionState, frozenset[SessionState]] = {
    SessionState.STARTED: frozenset({SessionState.ELIGIBILITY_OK, *TERMINAL_STATES}),
    SessionState.ELIGIBILITY_OK: frozenset({SessionState.CAPTURING, *TERMINAL_STATES}),
    SessionState.CAPTURING: frozenset({SessionState.REVIEWING, *TERMINAL_STATES}),
    SessionState.REVIEWING: frozenset({SessionState.DELIVERED, *TERMINAL_STATES}),
    # A delivered visit only ends: its photos are made and its link stays valid regardless.
    SessionState.DELIVERED: frozenset({SessionState.COMPLETED, SessionState.ERROR}),
    SessionState.COMPLETED: frozenset(),
    SessionState.CANCELLED: frozenset(),
    SessionState.ERROR: frozenset(),
    SessionState.ABANDONED: frozenset(),
}


# How an unfinished visit ends when nobody finishes it (a timeout, or the next guest starting):
# one whose photos were already made was delivered, so it is complete, not abandoned.
def closing_state(state: SessionState) -> SessionState:
    return SessionState.COMPLETED if state is SessionState.DELIVERED else SessionState.ABANDONED


def may_move(current: SessionState, target: SessionState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


class CaptureStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"
    REPLACED = "replaced"


class OutputStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"
    # A later render of the same output replaced it (Phase 9 decorations change the render).
    SUPERSEDED = "superseded"


class OperationStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class RetakeMode(StrEnum):
    NONE = "none"
    PER_PHOTO = "per_photo"
    ALL = "all"


@dataclass(frozen=True)
class LayoutOffer:
    """One photo size the event offered when the session started, with its frame pinned."""

    template_key: str
    template_version: int
    layout_label: str  # e.g. "2x6" written with a multiplication sign
    frame_id: str
    frame_sha256: str
    captures: int
    outputs: int


@dataclass(frozen=True)
class ProfileSnapshot:
    """The event as it was when the session started. Never re-read from the profile afterwards."""

    profile_id: str
    profile_revision: int
    countdown_seconds: int
    mirror: bool
    retake_mode: RetakeMode
    delivery_mode: str
    inactivity_timeout_s: int
    layouts: tuple[LayoutOffer, ...]

    def offer(self, frame_id: str) -> LayoutOffer:
        for layout in self.layouts:
            if layout.frame_id == frame_id:
                return layout
        raise FrameNotOfferedError(frame_id)


@dataclass(frozen=True)
class Selection:
    """The frame the participant confirmed: it fixes the template and the number of photos."""

    template_key: str
    template_version: int
    layout_label: str
    frame_id: str
    frame_sha256: str
    captures: int
    outputs: int

    @classmethod
    def of(cls, layout: LayoutOffer) -> Selection:
        return cls(
            template_key=layout.template_key,
            template_version=layout.template_version,
            layout_label=layout.layout_label,
            frame_id=layout.frame_id,
            frame_sha256=layout.frame_sha256,
            captures=layout.captures,
            outputs=layout.outputs,
        )


@dataclass(frozen=True)
class BoothSession:
    id: str
    device_id: str
    event_profile_id: str
    state: SessionState
    state_version: int
    profile: ProfileSnapshot
    selection: Selection | None
    expected_capture_count: int
    successful_capture_count: int
    failed_capture_attempts: int
    started_at: datetime
    last_activity_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
    eligibility: Mapping[str, str] | None = None
    # An organizer trying the booth from Admin, not a guest. Test visits and their photos are
    # scratch data: they are cleaned up when the test ends and swept when they go stale.
    is_test: bool = False

    @property
    def closed(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def countdown_seconds(self) -> int:
        return self.profile.countdown_seconds

    @property
    def mirror(self) -> bool:
        return self.profile.mirror

    @property
    def retake_mode(self) -> RetakeMode:
        return self.profile.retake_mode


@dataclass(frozen=True)
class CaptureAsset:
    id: str
    session_id: str
    operation_id: str
    shot_index: int
    attempt_no: int
    idempotency_key: str
    status: CaptureStatus
    storage_key: str | None
    sha256: str | None
    width: int
    height: int
    mirrored: bool
    captured_at: datetime
    failure_reason: str | None = None


@dataclass(frozen=True)
class OutputAsset:
    """One finished photo (a print, or one strip of a 2x6) made from the visit's own photos.

    It records exactly what it was made from: the ordered captures, the frame and its checksum,
    and the decoration, so the same inputs are never rendered twice and different ones never
    reuse an old file.
    """

    id: str
    session_id: str
    operation_id: str
    output_index: int
    status: OutputStatus
    render_fingerprint: str
    template_key: str
    template_version: int
    frame_id: str
    frame_sha256: str
    capture_ids: tuple[str, ...]
    storage_key: str | None
    sha256: str | None
    width: int
    height: int
    byte_size: int
    rendered_at: datetime
    decoration: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class Operation:
    """One client-proposed change, recorded so a repeated request never does the work twice."""

    id: str
    session_id: str
    idempotency_key: str
    kind: str
    fingerprint: str
    status: OperationStatus
    owner_boot_id: str
    result_ref: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class DeviceOperation:
    """The same, for creating a session (which has no session id yet)."""

    id: str
    device_id: str
    idempotency_key: str
    fingerprint: str
    status: OperationStatus
    result_ref: str | None = None


@dataclass(frozen=True)
class ShotProgress:
    """What the booth screen needs to show for one photo of the session."""

    shot_index: int
    attempt_no: int
    done: bool
    # The photo that counts for this shot, so the screen can show it back to the guest.
    capture_id: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class CaptureOutcome:
    """The result of publishing one photo, whether it was just made or replayed."""

    capture: CaptureAsset
    session: BoothSession


@dataclass(frozen=True)
class CaptureFacts:
    """What the server checked about the received photo."""

    width: int
    height: int
    sha256: str


@dataclass(frozen=True)
class RenderOutcome:
    """The finished photos of a visit, whether just made or replayed."""

    session: BoothSession
    outputs: tuple[OutputAsset, ...]


@dataclass(frozen=True)
class RenderPhoto:
    """One original photo handed to the renderer, in shot order."""

    capture_id: str
    shot_index: int
    data: bytes


@dataclass(frozen=True)
class RenderRequest:
    template_key: str
    template_version: int
    frame_png: bytes
    mirror: bool
    photos: tuple[RenderPhoto, ...]
    decoration: str | None = None


@dataclass(frozen=True)
class RenderedFile:
    output_index: int
    data: bytes
    width: int
    height: int
    capture_ids: tuple[str, ...]


@dataclass(frozen=True)
class DeliveryLink:
    """What the booth shows so the guest can take the photos home. `url` holds the secret."""

    url: str
    expires_at: datetime
    qr_svg: str


@dataclass(frozen=True)
class EligibilityDecision:
    allowed: bool
    reason: str | None = None
    details: Mapping[str, str] | None = None


class EligibilityProvider(Protocol):
    """Whether this device may start a session (a placeholder until Reconize is wired in)."""

    def check(self, device_id: str, profile_id: str) -> EligibilityDecision: ...


class ActiveEvent(Protocol):
    """An Event Profile flattened for a snapshot (from the event_profiles module).

    `profile_id` is None for the event the booth is running; the Admin test names a saved profile
    instead, which is read but never activated or changed.
    """

    def snapshot(self, profile_id: str | None = None) -> ProfileSnapshot | None: ...


class CaptureImages(Protocol):
    """Reading the bytes of a photo (from the assets module): format, size and checksum."""

    def inspect(self, data: bytes) -> CaptureFacts: ...


class CaptureFiles(Protocol):
    """Where photos are kept (the storage module); keys are server-made, never client input."""

    def put(self, key: str, data: bytes) -> None: ...

    def exists(self, key: str) -> bool: ...

    def read(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class OutputRenderer(Protocol):
    """Makes the finished photos (the rendering module, on its single render worker).

    Raises RenderBusyError when the worker is full (nothing started) and RenderFailedError when
    these inputs can not be rendered.
    """

    def render(self, request: RenderRequest) -> list[RenderedFile]: ...


class SessionFrames(Protocol):
    """The bytes of a frame file (the frames module). A visit only ever uses its pinned frame."""

    def frame_png(self, frame_id: str) -> bytes: ...


class DeliveryLinks(Protocol):
    """The guest's take-home link for a visit (the delivery module).

    Called while the session is locked, so two simultaneous requests get the same link.
    """

    def ensure(self, session_id: str) -> DeliveryLink: ...


def capture_key(session_id: str, capture_id: str) -> str:
    return f"captures/{session_id}/{capture_id}.jpg"


def output_key(session_id: str, output_id: str) -> str:
    return f"outputs/{session_id}/{output_id}.jpg"


class SessionRepository(ABC):
    """Every method is one transaction; the database is the source of truth."""

    @abstractmethod
    def device_operation(self, device_id: str, key: str) -> DeviceOperation | None: ...

    @abstractmethod
    def create(self, session: BoothSession, operation: DeviceOperation) -> BoothSession:
        """Abandon this device's previous unfinished session and record the new one."""

    @abstractmethod
    def get(self, session_id: str) -> BoothSession | None: ...

    @abstractmethod
    def active_for_device(self, device_id: str) -> BoothSession | None: ...

    @abstractmethod
    def touch(self, session_id: str, at: datetime) -> None:
        """Keep the session alive (inactivity is measured from the last participant action)."""

    @abstractmethod
    def operation(self, session_id: str, key: str) -> Operation | None: ...

    @abstractmethod
    def capture(self, capture_id: str) -> CaptureAsset | None: ...

    @abstractmethod
    def captures(self, session_id: str) -> list[CaptureAsset]: ...

    @abstractmethod
    def select_frame(
        self, session_id: str, expected_version: int, selection: Selection, at: datetime
    ) -> BoothSession:
        """Pin the chosen frame and enter capturing, in one transaction."""

    @abstractmethod
    def start_capture(self, capture: CaptureAsset, operation: Operation, at: datetime) -> None:
        """T1: record the pending photo and its operation before the file is published."""

    @abstractmethod
    def finalize_capture(self, operation_id: str, facts: CaptureFacts) -> CaptureOutcome:
        """T2: the photo counts only if its shot still wants this attempt."""

    @abstractmethod
    def fail_capture(self, operation_id: str, code: str) -> CaptureOutcome:
        """Mark the attempt failed and its file for deletion; counters are untouched."""

    @abstractmethod
    def allocate_retake(
        self, session_id: str, expected_version: int, shots: Sequence[int], at: datetime
    ) -> BoothSession:
        """Replace the photos of these shots so their next attempt is the one that counts."""

    @abstractmethod
    def finish_capturing(
        self, session_id: str, expected_version: int, at: datetime
    ) -> BoothSession:
        """Every photo is there: move on to the review step."""

    @abstractmethod
    def close(
        self,
        session_id: str,
        state: SessionState,
        at: datetime,
        code: str | None = None,
        idle_since: datetime | None = None,
    ) -> BoothSession | None:
        """`idle_since` only closes a visit nobody has touched since that moment."""

    @abstractmethod
    def close_inactive(self, now: datetime) -> list[str]:
        """End every session whose own inactivity timeout has passed. Returns their ids."""

    @abstractmethod
    def pinned_frames(self) -> set[str]:
        """Frames that visits in progress depend on; their files may not be replaced or removed."""

    @abstractmethod
    def finished_test_sessions(self, before: datetime) -> list[str]:
        """Test visits that ended, or went stale, and may be cleared away. Never a guest's."""

    @abstractmethod
    def forget_test_session(self, session_id: str) -> list[str]:
        """Remove a test visit and its rows; returns the files that belonged to it."""

    @abstractmethod
    def unfinished_operations(self, boot_id: str) -> list[Operation]:
        """Pending operations left behind by a process that is gone."""

    @abstractmethod
    def files_to_delete(self) -> list[tuple[str, str]]: ...

    @abstractmethod
    def mark_file_deleted(self, capture_id: str, at: datetime) -> None: ...

    # ---- finished photos -----------------------------------------------------------------

    @abstractmethod
    def output(self, output_id: str) -> OutputAsset | None: ...

    @abstractmethod
    def outputs(self, session_id: str) -> list[OutputAsset]:
        """Every output row of the visit, in output order (any status)."""

    @abstractmethod
    def start_render(
        self, operation: Operation, outputs: Sequence[OutputAsset], at: datetime
    ) -> None:
        """T1: record the pending outputs and their operation before any file is published."""

    @abstractmethod
    def finalize_render(self, operation_id: str, fingerprint: str) -> RenderOutcome:
        """T2: the outputs count only if the visit is still reviewing with these same inputs."""

    @abstractmethod
    def fail_render(self, operation_id: str, code: str) -> RenderOutcome:
        """Mark the outputs failed and their files for deletion."""

    @abstractmethod
    def output_files_to_delete(self) -> list[tuple[str, str]]: ...

    @abstractmethod
    def mark_output_file_deleted(self, output_id: str, at: datetime) -> None: ...
