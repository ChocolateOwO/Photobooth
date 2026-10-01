"""Booth session use cases: start a visit, take its photos, retake, give up, recover.

One booth runs one backend process, so a per-session lock is enough to make every change to a
session happen one at a time. A repeated request (a lost answer, a double tap, a reload) never
does the work twice: each change carries an idempotency key whose recorded outcome is replayed.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from weakref import WeakValueDictionary

from photobooth.modules.sessions.domain import (
    MAX_ATTEMPTS_PER_SHOT,
    ActiveEvent,
    BoothSession,
    CaptureAsset,
    CaptureFacts,
    CaptureFiles,
    CaptureImages,
    CaptureNotFoundError,
    CaptureOutcome,
    CaptureRefusedError,
    CaptureStatus,
    Clock,
    DeliveryLink,
    DeliveryLinks,
    DeviceOperation,
    EligibilityProvider,
    EligibilityRefusedError,
    IdempotencyReuseError,
    NoActiveEventError,
    Operation,
    OperationFailedError,
    OperationStatus,
    OutputAsset,
    OutputNotFoundError,
    OutputRenderer,
    OutputStatus,
    RenderFailedError,
    RenderOutcome,
    RenderPhoto,
    RenderRequest,
    RetakeMode,
    Selection,
    SessionClosedError,
    SessionFrames,
    SessionNotFoundError,
    SessionRepository,
    SessionState,
    ShotProgress,
    StaleAttemptError,
    StaleSessionError,
    TooManyCapturesError,
    TransitionRefusedError,
    capture_key,
    may_move,
    output_key,
)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SessionLocks:
    """One lock per session id, kept only while somebody holds or waits for it."""

    def __init__(self) -> None:
        self._locks: WeakValueDictionary[str, threading.RLock] = WeakValueDictionary()
        self._guard = threading.Lock()

    @contextmanager
    def held(self, session_id: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[session_id] = lock
        with lock:
            yield


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def render_fingerprint(
    selection: Selection, captures: Sequence[CaptureAsset], mirror: bool, decoration: str | None
) -> str:
    """Everything a finished photo is made from. Same inputs, same photo; any change, a new one."""
    return _fingerprint(
        "render",
        selection.template_key,
        selection.template_version,
        selection.frame_id,
        selection.frame_sha256,
        ",".join(f"{c.shot_index}:{c.id}:{c.sha256}" for c in captures),
        mirror,
        hashlib.sha256((decoration or "").encode()).hexdigest(),
    )


class BoothSessionService:
    """Everything the participant screens may do with a session."""

    def __init__(
        self,
        repository: SessionRepository,
        event: ActiveEvent,
        images: CaptureImages,
        files: CaptureFiles,
        eligibility: EligibilityProvider,
        boot_id: str,
        *,
        renderer: OutputRenderer,
        frames: SessionFrames,
        links: DeliveryLinks,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._event = event
        self._images = images
        self._files = files
        self._eligibility = eligibility
        self._boot_id = boot_id
        self._renderer = renderer
        self._frames = frames
        self._links = links
        self._clock = clock or SystemClock()
        self._locks = SessionLocks()
        self._device_locks = SessionLocks()

    # ---- starting and reading -------------------------------------------------------------

    def start(
        self,
        device_id: str,
        idempotency_key: str,
        profile_id: str | None = None,
        is_test: bool = False,
    ) -> BoothSession:
        """Begin a visit. A repeated key returns the same session.

        `profile_id` and `is_test` belong to the Admin "Test booth" page: the organizer tries a
        saved profile with the real camera, and that visit is scratch data from the start.
        """
        with self._device_locks.held(device_id):
            # Visits nobody came back to are ended first, so the booth starts from a clean slate.
            self._repository.close_inactive(self._clock.now())
            if is_test:
                self.clear_old_tests()
            snapshot = self._event.snapshot(profile_id)
            if snapshot is None:
                raise NoActiveEventError()
            fingerprint = _fingerprint("session", snapshot.profile_id, is_test)
            recorded = self._repository.device_operation(device_id, idempotency_key)
            if recorded is not None:
                if recorded.fingerprint != fingerprint:
                    raise IdempotencyReuseError()
                existing = (
                    self._repository.get(recorded.result_ref) if recorded.result_ref else None
                )
                if existing is not None:
                    return existing
            decision = self._eligibility.check(device_id, snapshot.profile_id)
            if not decision.allowed:
                raise EligibilityRefusedError(decision.reason or "this booth can not start a visit")
            now = self._clock.now()
            session = BoothSession(
                id=str(uuid.uuid4()),
                device_id=device_id,
                event_profile_id=snapshot.profile_id,
                # The placeholder provider allows everyone, so the visit starts already checked.
                state=SessionState.ELIGIBILITY_OK,
                state_version=1,
                profile=snapshot,
                selection=None,
                expected_capture_count=0,
                successful_capture_count=0,
                failed_capture_attempts=0,
                started_at=now,
                last_activity_at=now,
                eligibility=dict(decision.details or {}),
                is_test=is_test,
            )
            operation = DeviceOperation(
                id=str(uuid.uuid4()),
                device_id=device_id,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                status=OperationStatus.DONE,
                result_ref=session.id,
            )
            return self._repository.create(session, operation)

    def current(self, device_id: str) -> BoothSession | None:
        """The visit this device is in the middle of, if any (used after a reload)."""
        session = self._repository.active_for_device(device_id)
        if session is None:
            return None
        # A visit nobody came back to ends here rather than waiting for the next guest.
        settled = self._closed_if_inactive(session)
        return None if settled.closed else settled

    def read(self, device_id: str, session_id: str) -> BoothSession:
        return self._load(device_id, session_id, allow_closed=True)

    def progress(self, session_id: str) -> list[ShotProgress]:
        """Which photo is next and how far the session has come.

        A visit that is gone (a test the organizer just cleared away) simply has no photos left
        to describe.
        """
        session = self._repository.get(session_id)
        if session is None:
            return []
        done: dict[int, CaptureAsset] = {}
        attempts: dict[int, int] = {}
        for capture in self._repository.captures(session_id):
            attempts[capture.shot_index] = max(
                attempts.get(capture.shot_index, 0), capture.attempt_no
            )
            if capture.status is CaptureStatus.OK:
                done[capture.shot_index] = capture
        # Each shot carries the photo that counts for it, so a screen can never show the picture
        # of another shot (a shot with no photo carries nothing at all).
        # For a photo still to be taken this is the attempt the booth must send next (a retake
        # moves it on); for one already taken, the attempt that counted.
        return [
            ShotProgress(
                shot_index=shot,
                attempt_no=(done[shot].attempt_no if shot in done else attempts.get(shot, 0) + 1),
                done=shot in done,
                capture_id=done[shot].id if shot in done else None,
                version=(done[shot].sha256 or "")[:16] if shot in done else None,
            )
            for shot in range(1, session.expected_capture_count + 1)
        ]

    # ---- choosing the frame ----------------------------------------------------------------

    def choose_frame(self, device_id: str, session_id: str, frame_id: str) -> BoothSession:
        """Confirm the frame: it pins the template and how many photos the session takes."""
        with self._locks.held(session_id):
            session = self._load(device_id, session_id)
            if session.selection is not None:
                if session.selection.frame_id != frame_id:
                    raise TransitionRefusedError("this session already has its frame")
                return session
            if not may_move(session.state, SessionState.CAPTURING):
                raise TransitionRefusedError(f"a {session.state} session can not start photos")
            selection = Selection.of(session.profile.offer(frame_id))
            return self._repository.select_frame(
                session_id, session.state_version, selection, self._clock.now()
            )

    # ---- photos ------------------------------------------------------------------------------

    def add_capture(
        self,
        device_id: str,
        session_id: str,
        *,
        idempotency_key: str,
        shot_index: int,
        attempt_no: int,
        data: bytes,
    ) -> CaptureOutcome:
        """Publish one photo. The same key twice returns the first answer and stores nothing."""
        with self._locks.held(session_id):
            # The device that owns the visit is established before anything is looked up, so a
            # second paired browser can not replay somebody else's photo or read their visit
            # (P67-001).
            self._owned(device_id, session_id)
            fingerprint = _fingerprint(
                "capture", session_id, shot_index, attempt_no, hashlib.sha256(data).hexdigest()
            )
            replay = self._replay(session_id, idempotency_key, fingerprint)
            if replay is not None:
                return replay

            session = self._load(device_id, session_id)
            if session.state is not SessionState.CAPTURING or session.selection is None:
                raise TransitionRefusedError("this session is not taking photos")
            if not 1 <= shot_index <= session.expected_capture_count:
                raise TransitionRefusedError(
                    f"this session takes photos 1 to {session.expected_capture_count}"
                )
            self._check_attempt(session_id, shot_index, attempt_no)

            facts = self._images.inspect(data)
            capture_id = str(uuid.uuid4())
            key = capture_key(session_id, capture_id)
            now = self._clock.now()
            operation = Operation(
                id=str(uuid.uuid4()),
                session_id=session_id,
                idempotency_key=idempotency_key,
                kind="capture",
                fingerprint=fingerprint,
                status=OperationStatus.PENDING,
                owner_boot_id=self._boot_id,
            )
            capture = CaptureAsset(
                id=capture_id,
                session_id=session_id,
                operation_id=operation.id,
                shot_index=shot_index,
                attempt_no=attempt_no,
                idempotency_key=idempotency_key,
                status=CaptureStatus.PENDING,
                storage_key=key,
                sha256=facts.sha256,
                width=facts.width,
                height=facts.height,
                # The photo is stored exactly as the camera made it; the mirror is a render
                # setting, so what was on the preview is reproduced later, not baked in now.
                mirrored=session.mirror,
                captured_at=now,
            )
            self._repository.start_capture(capture, operation, now)
            try:
                self._files.put(key, data)
            except Exception:
                self._repository.fail_capture(operation.id, "file_not_stored")
                self._collect_files()
                raise
            outcome = self._repository.finalize_capture(operation.id, facts)
            if outcome.capture.status is not CaptureStatus.OK:
                self._collect_files()
            return outcome

    def retake(
        self,
        device_id: str,
        session_id: str,
        shots: Sequence[int] | None = None,
        expected_version: int | None = None,
    ) -> BoothSession:
        """Take a photo (or the whole set) again, as the event's retake setting allows.

        The client says which version of the visit it is answering, so a second tap that arrives
        after a new photo was taken is refused instead of throwing that photo away (P67-006).
        """
        with self._locks.held(session_id):
            session = self._load(device_id, session_id)
            if expected_version is not None and expected_version != session.state_version:
                raise StaleSessionError()
            if session.state is not SessionState.CAPTURING:
                raise TransitionRefusedError("this session is not taking photos")
            mode = session.retake_mode
            if mode is RetakeMode.NONE:
                raise TransitionRefusedError("this event does not allow retakes")
            wanted = list(shots or range(1, session.expected_capture_count + 1))
            if mode is RetakeMode.PER_PHOTO and len(wanted) != 1:
                raise TransitionRefusedError("this event retakes one photo at a time")
            if mode is RetakeMode.ALL and len(wanted) != session.expected_capture_count:
                raise TransitionRefusedError("this event retakes all the photos together")
            if any(not 1 <= shot <= session.expected_capture_count for shot in wanted):
                raise TransitionRefusedError("that photo is not part of this session")
            taken = {
                capture.shot_index
                for capture in self._repository.captures(session_id)
                if capture.status is CaptureStatus.OK
            }
            if any(shot not in taken for shot in wanted):
                raise TransitionRefusedError("that photo has not been taken yet")
            for shot in wanted:
                self._check_attempt_room(session_id, shot)
            return self._repository.allocate_retake(
                session_id, session.state_version, wanted, self._clock.now()
            )

    def finish_capturing(self, device_id: str, session_id: str) -> BoothSession:
        """All photos are in: the session leaves the camera behind (review comes next phase)."""
        with self._locks.held(session_id):
            session = self._load(device_id, session_id)
            if session.state is not SessionState.CAPTURING:
                raise TransitionRefusedError("this session is not taking photos")
            if session.successful_capture_count < session.expected_capture_count:
                raise TransitionRefusedError("some photos are still missing")
            return self._repository.finish_capturing(
                session_id, session.state_version, self._clock.now()
            )

    def give_up(self, device_id: str, session_id: str) -> BoothSession:
        """The participant leaves: the session ends and nothing more may be added to it."""
        with self._locks.held(session_id):
            session = self._repository.get(session_id)
            if session is None or session.device_id != device_id:
                raise SessionNotFoundError()
            if session.closed:
                self._clear_test(session)
                return session
            # Leaving after the photos were delivered is simply the end of the visit.
            ending = (
                SessionState.COMPLETED
                if session.state is SessionState.DELIVERED
                else SessionState.CANCELLED
            )
            closed = self._repository.close(session_id, ending, self._clock.now())
            settled = closed or session
            self._clear_test(settled)
            return settled

    def photo(self, device_id: str, session_id: str, capture_id: str) -> bytes:
        """One photo of this visit, for the screen that took it. Only its own device may see it."""
        with self._locks.held(session_id):
            self._owned(device_id, session_id)
            capture = self._repository.capture(capture_id)
            if (
                capture is None
                or capture.session_id != session_id
                or capture.status is not CaptureStatus.OK
                or capture.storage_key is None
            ):
                raise CaptureNotFoundError()
            try:
                return self._files.read(capture.storage_key)
            except Exception as exc:  # a stored photo that vanished is not a 500 for the booth
                raise CaptureNotFoundError() from exc

    # ---- finished photos and delivery ---------------------------------------------------------

    def render(
        self,
        device_id: str,
        session_id: str,
        idempotency_key: str,
        decoration: str | None = None,
    ) -> RenderOutcome:
        """Make the finished photos from the visit's own photos and its pinned frame.

        Exactly once: the same key replays the first answer, and a second request with another
        key (a double tap, a reload) finds the photos already made. Rendering runs on the single
        render worker; when it is full nothing is recorded and the same request may be retried.
        """
        with self._locks.held(session_id):
            self._owned(device_id, session_id)
            request_fingerprint = _fingerprint(
                "render-request",
                session_id,
                hashlib.sha256((decoration or "").encode()).hexdigest(),
            )
            replay = self._replay_render(session_id, idempotency_key, request_fingerprint)
            if replay is not None:
                return replay

            session = self._load(device_id, session_id)
            if session.state is SessionState.DELIVERED:
                return self._delivered(session)
            if session.state is not SessionState.REVIEWING or session.selection is None:
                raise TransitionRefusedError("this session is not ready for its finished photos")
            selection = session.selection
            captures = self._counted_captures(session)
            fingerprint = render_fingerprint(selection, captures, session.mirror, decoration)

            try:
                frame_png = self._frames.frame_png(selection.frame_id)
                if hashlib.sha256(frame_png).hexdigest() != selection.frame_sha256:
                    raise RenderFailedError("frame_changed")
                photos = tuple(
                    RenderPhoto(
                        capture_id=capture.id,
                        shot_index=capture.shot_index,
                        data=self._files.read(capture.storage_key or ""),
                    )
                    for capture in captures
                )
                files = self._renderer.render(
                    RenderRequest(
                        template_key=selection.template_key,
                        template_version=selection.template_version,
                        frame_png=frame_png,
                        mirror=session.mirror,
                        photos=photos,
                        decoration=decoration,
                    )
                )
            except RenderFailedError as exc:
                # Nothing about this visit can be made: it ends, and the booth starts over.
                self._repository.close(session_id, SessionState.ERROR, self._clock.now(), exc.code)
                raise
            except (FileNotFoundError, OSError) as exc:
                self._repository.close(
                    session_id, SessionState.ERROR, self._clock.now(), "photo_missing"
                )
                raise RenderFailedError("photo_missing") from exc

            now = self._clock.now()
            operation = Operation(
                id=str(uuid.uuid4()),
                session_id=session_id,
                idempotency_key=idempotency_key,
                kind="render",
                fingerprint=request_fingerprint,
                status=OperationStatus.PENDING,
                owner_boot_id=self._boot_id,
            )
            outputs: list[OutputAsset] = []
            for file in files:
                output_id = str(uuid.uuid4())
                outputs.append(
                    OutputAsset(
                        id=output_id,
                        session_id=session_id,
                        operation_id=operation.id,
                        output_index=file.output_index,
                        status=OutputStatus.PENDING,
                        render_fingerprint=fingerprint,
                        template_key=selection.template_key,
                        template_version=selection.template_version,
                        frame_id=selection.frame_id,
                        frame_sha256=selection.frame_sha256,
                        capture_ids=file.capture_ids,
                        storage_key=output_key(session_id, output_id),
                        sha256=hashlib.sha256(file.data).hexdigest(),
                        width=file.width,
                        height=file.height,
                        byte_size=len(file.data),
                        rendered_at=now,
                        decoration=decoration,
                    )
                )
            self._repository.start_render(operation, outputs, now)
            try:
                for output, file in zip(outputs, files, strict=True):
                    self._files.put(output.storage_key or "", file.data)
            except Exception:
                self._repository.fail_render(operation.id, "file_not_stored")
                self._collect_files()
                raise
            outcome = self._repository.finalize_render(operation.id, fingerprint)
            if any(output.status is not OutputStatus.OK for output in outcome.outputs):
                self._collect_files()
            return outcome

    def finished_outputs(self, session_id: str) -> list[OutputAsset]:
        """The finished photos that count for a visit, in output order."""
        return [
            output
            for output in self._repository.outputs(session_id)
            if output.status is OutputStatus.OK
        ]

    def output_photo(self, device_id: str, session_id: str, output_id: str) -> bytes:
        """One finished photo, for the booth screen of the visit that made it."""
        with self._locks.held(session_id):
            self._owned(device_id, session_id)
            output = self._repository.output(output_id)
            if (
                output is None
                or output.session_id != session_id
                or output.status is not OutputStatus.OK
                or output.storage_key is None
            ):
                raise OutputNotFoundError()
            try:
                return self._files.read(output.storage_key)
            except Exception as exc:  # a stored photo that vanished is not a 500 for the booth
                raise OutputNotFoundError() from exc

    def delivery_link(self, device_id: str, session_id: str) -> DeliveryLink:
        """The take-home link and QR code for a delivered visit.

        Issued while the session is locked, so a double tap or a reload never makes two links.
        """
        with self._locks.held(session_id):
            session = self._load(device_id, session_id)
            if session.state is not SessionState.DELIVERED:
                raise TransitionRefusedError("the finished photos are not ready yet")
            return self._links.ensure(session_id)

    def clear_old_tests(self, keep_for_seconds: int = 3600) -> int:
        """Clear away the organizer's finished or forgotten test visits. Never a guest's."""
        cutoff = self._clock.now() - timedelta(seconds=keep_for_seconds)
        cleared = 0
        for session_id in self._repository.finished_test_sessions(cutoff):
            with self._locks.held(session_id):
                for key in self._repository.forget_test_session(session_id):
                    self._files.delete(key)
                cleared += 1
        return cleared

    def _clear_test(self, session: BoothSession) -> None:
        """A test visit leaves nothing behind once the organizer has finished with it."""
        if not session.is_test:
            return
        for key in self._repository.forget_test_session(session.id):
            self._files.delete(key)

    # ---- keeping the booth honest --------------------------------------------------------

    def close_inactive(self) -> list[str]:
        """End every session nobody has touched within its event's inactivity timeout."""
        return self._repository.close_inactive(self._clock.now())

    def pinned_frames(self) -> set[str]:
        """Frames a visit in progress depends on (its own and the ones its event offered)."""
        return self._repository.pinned_frames()

    def recover(self) -> int:
        """After a restart: settle photos and finished photos left half-published, and delete
        files nobody wants."""
        settled = 0
        for operation in self._repository.unfinished_operations(self._boot_id):
            with self._locks.held(operation.session_id):
                if operation.kind == "render":
                    self._settle_render(operation)
                else:
                    self._settle_capture(operation)
                settled += 1
        self._collect_files()
        return settled

    def maintain(self) -> None:
        """Periodic upkeep while the booth runs: end visits nobody came back to, sweep stale
        organizer tests, settle anything a dead process left behind and work off the deletion
        ledger. Every step is idempotent."""
        self.close_inactive()
        self.clear_old_tests()
        self.recover()

    # ---- internals ---------------------------------------------------------------------------

    def _facts_of(self, capture: CaptureAsset) -> CaptureFacts:
        return CaptureFacts(width=capture.width, height=capture.height, sha256=capture.sha256 or "")

    def _settle_capture(self, operation: Operation) -> None:
        capture = self._repository.capture(operation.result_ref or "")
        stored = capture.storage_key if capture else None
        if (
            capture is not None
            and stored is not None
            and capture.sha256 is not None
            and self._files.exists(stored)
        ):
            self._repository.finalize_capture(operation.id, self._facts_of(capture))
        else:
            self._repository.fail_capture(operation.id, "file_not_stored")

    def _settle_render(self, operation: Operation) -> None:
        """Finish a render whose publisher is gone: it counts only if every file is there, intact,
        and made from what the visit still holds."""
        session = self._repository.get(operation.session_id)
        mine = [
            output
            for output in self._repository.outputs(operation.session_id)
            if output.operation_id == operation.id
        ]
        intact = bool(mine) and all(self._intact(output) for output in mine)
        if session is None or session.selection is None or not intact:
            self._repository.fail_render(operation.id, "file_not_stored")
            return
        current = render_fingerprint(
            session.selection,
            self._counted_captures(session),
            session.mirror,
            mine[0].decoration,
        )
        self._repository.finalize_render(operation.id, current)

    def _intact(self, output: OutputAsset) -> bool:
        if output.storage_key is None or output.sha256 is None:
            return False
        try:
            data = self._files.read(output.storage_key)
        except Exception:
            return False
        return hashlib.sha256(data).hexdigest() == output.sha256

    def _counted_captures(self, session: BoothSession) -> list[CaptureAsset]:
        """The photo that counts for each shot, in shot order."""
        return sorted(
            (
                capture
                for capture in self._repository.captures(session.id)
                if capture.status is CaptureStatus.OK
            ),
            key=lambda capture: capture.shot_index,
        )

    def _delivered(self, session: BoothSession) -> RenderOutcome:
        return RenderOutcome(session=session, outputs=tuple(self.finished_outputs(session.id)))

    def _replay_render(self, session_id: str, key: str, fingerprint: str) -> RenderOutcome | None:
        recorded = self._repository.operation(session_id, key)
        if recorded is None:
            return None
        if recorded.fingerprint != fingerprint or recorded.kind != "render":
            raise IdempotencyReuseError()
        if recorded.status is OperationStatus.PENDING:
            # Its publisher is gone (this process holds the lock): settle it before answering.
            self._settle_render(recorded)
            self._collect_files()
            recorded = self._repository.operation(session_id, key) or recorded
        if recorded.status is OperationStatus.FAILED:
            raise OperationFailedError(recorded.failure_code or "render_failed")
        session = self._repository.get(session_id)
        if session is None:
            raise SessionNotFoundError()
        return self._delivered(session)

    def _collect_files(self) -> None:
        """Delete the files of photos that never counted (idempotent; a missing file is fine)."""
        for capture_id, key in self._repository.files_to_delete():
            self._files.delete(key)
            self._repository.mark_file_deleted(capture_id, self._clock.now())
        for output_id, key in self._repository.output_files_to_delete():
            self._files.delete(key)
            self._repository.mark_output_file_deleted(output_id, self._clock.now())

    def _replay(self, session_id: str, key: str, fingerprint: str) -> CaptureOutcome | None:
        recorded = self._repository.operation(session_id, key)
        if recorded is None:
            return None
        if recorded.fingerprint != fingerprint:
            raise IdempotencyReuseError()
        if recorded.status is OperationStatus.PENDING:
            # Its publisher is gone (this process holds the lock): settle it before answering.
            capture = self._repository.capture(recorded.result_ref or "")
            stored = capture.storage_key if capture else None
            if capture is not None and stored is not None and self._files.exists(stored):
                self._repository.finalize_capture(recorded.id, self._facts_of(capture))
            else:
                self._repository.fail_capture(recorded.id, "file_not_stored")
            self._collect_files()
            recorded = self._repository.operation(session_id, key) or recorded
        if recorded.status is OperationStatus.FAILED:
            raise OperationFailedError(recorded.failure_code or "capture_failed")
        capture = self._repository.capture(recorded.result_ref or "")
        session = self._repository.get(session_id)
        if capture is None or session is None:
            raise SessionNotFoundError()
        return CaptureOutcome(capture=capture, session=session)

    def _check_attempt(self, session_id: str, shot_index: int, attempt_no: int) -> None:
        captures = [
            capture
            for capture in self._repository.captures(session_id)
            if capture.shot_index == shot_index
        ]
        if any(capture.status is CaptureStatus.OK for capture in captures):
            raise StaleAttemptError(shot_index, max(c.attempt_no for c in captures))
        expected = max((capture.attempt_no for capture in captures), default=0) + 1
        # A photo that was never taken starts at attempt 1; a retake moves the number on.
        if attempt_no != expected:
            raise StaleAttemptError(shot_index, expected)
        if attempt_no > MAX_ATTEMPTS_PER_SHOT:
            raise TooManyCapturesError(shot_index)

    def _check_attempt_room(self, session_id: str, shot_index: int) -> None:
        attempts = [
            capture.attempt_no
            for capture in self._repository.captures(session_id)
            if capture.shot_index == shot_index
        ]
        if max(attempts, default=0) + 1 > MAX_ATTEMPTS_PER_SHOT:
            raise TooManyCapturesError(shot_index)

    def _owned(self, device_id: str, session_id: str) -> BoothSession:
        """The visit, if it belongs to this device. Nothing else may see it exists."""
        session = self._repository.get(session_id)
        if session is None or session.device_id != device_id:
            raise SessionNotFoundError()
        return session

    def _load(self, device_id: str, session_id: str, allow_closed: bool = False) -> BoothSession:
        session = self._repository.get(session_id)
        if session is None or session.device_id != device_id:
            raise SessionNotFoundError()
        session = self._closed_if_inactive(session)
        if session.closed and not allow_closed:
            raise SessionClosedError(session.state)
        if not session.closed:
            now = self._clock.now()
            self._repository.touch(session_id, now)
        return session

    def _closed_if_inactive(self, session: BoothSession) -> BoothSession:
        """Nobody at the booth for the whole timeout: the session is over, server-side first."""
        if session.closed:
            return session
        idle = (self._clock.now() - session.last_activity_at).total_seconds()
        if idle < session.profile.inactivity_timeout_s:
            return session
        # Closed only while nobody has touched the visit since it was read (P67-008).
        return (
            self._repository.close(
                session.id,
                SessionState.ABANDONED,
                self._clock.now(),
                "inactivity",
                idle_since=session.last_activity_at,
            )
            or session
        )


__all__ = [
    "BoothSessionService",
    "CaptureRefusedError",
    "SessionLocks",
    "StaleSessionError",
    "SystemClock",
]
