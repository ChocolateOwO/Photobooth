"""SQLAlchemy SessionRepository.

Invariants the database keeps, not only the service:
- a device has at most one unfinished session (partial unique index on device_id);
- one photo per shot counts (partial unique index on (session_id, shot_index) where status='ok');
- an attempt exists once per shot (unique (session_id, shot_index, attempt_no));
- an idempotency key belongs to one request (unique (session_id, idempotency_key), and
  (device_id, idempotency_key) for starting a session);
- a session can not count more photos than it expects (check constraint).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Engine,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from photobooth.core.db import Base, UtcDateTime
from photobooth.modules.sessions.domain import (
    BoothSession,
    CaptureAsset,
    CaptureFacts,
    CaptureOutcome,
    CaptureStatus,
    DeviceOperation,
    LayoutOffer,
    Operation,
    OperationStatus,
    OutputAsset,
    OutputStatus,
    ProfileSnapshot,
    RenderOutcome,
    RetakeMode,
    Selection,
    SessionNotFoundError,
    SessionRepository,
    SessionState,
    StaleSessionError,
    TransitionRefusedError,
    VisitFacts,
    closing_state,
)


class BoothSessionRow(Base):
    __tablename__ = "booth_sessions"
    __table_args__ = (
        CheckConstraint(
            "successful_capture_count <= expected_capture_count",
            name="ck_booth_sessions_capture_count",
        ),
        CheckConstraint("state_version >= 1", name="ck_booth_sessions_state_version"),
        # One unfinished session per device, enforced by the database itself.
        Index(
            "uq_booth_sessions_open_device",
            "device_id",
            unique=True,
            sqlite_where=text("state NOT IN ('completed', 'cancelled', 'error', 'abandoned')"),
        ),
        Index("ix_booth_sessions_state", "state"),
        # The organizer's test visits are found (and cleared away) without reading the guests'.
        Index("ix_booth_sessions_test", "is_test", sqlite_where=text("is_test = 1")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    profile_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    selection_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_capture_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful_capture_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_capture_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligibility_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CaptureAssetRow(Base):
    __tablename__ = "capture_assets"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "shot_index", "attempt_no", name="uq_capture_assets_attempt"
        ),
        UniqueConstraint("session_id", "idempotency_key", name="uq_capture_assets_key"),
        CheckConstraint("shot_index >= 1", name="ck_capture_assets_shot"),
        CheckConstraint("attempt_no >= 1", name="ck_capture_assets_attempt"),
        # Exactly one photo per shot ever counts, whatever a client sends.
        Index(
            "uq_capture_assets_shot_ok",
            "session_id",
            "shot_index",
            unique=True,
            sqlite_where=text("status = 'ok'"),
        ),
        # The files still to be deleted are looked up often and are few.
        Index(
            "ix_capture_assets_delete_pending",
            "file_delete_pending",
            sqlite_where=text("file_delete_pending = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("booth_sessions.id", ondelete="CASCADE"), nullable=False
    )
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    shot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    mirrored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    captured_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_delete_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    file_deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class OutputAssetRow(Base):
    __tablename__ = "output_assets"
    __table_args__ = (
        CheckConstraint("output_index >= 1", name="ck_output_assets_index"),
        # One finished photo per output of a visit counts, however often it is requested.
        Index(
            "uq_output_assets_index_ok",
            "session_id",
            "output_index",
            unique=True,
            sqlite_where=text("status = 'ok'"),
        ),
        Index("ix_output_assets_session", "session_id"),
        Index("ix_output_assets_operation", "operation_id"),
        Index(
            "ix_output_assets_delete_pending",
            "file_delete_pending",
            sqlite_where=text("file_delete_pending = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("booth_sessions.id", ondelete="CASCADE"), nullable=False
    )
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    output_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    render_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # No foreign key: a finished photo outlives its frame; the checksum says which file it was.
    frame_id: Mapped[str] = mapped_column(String(36), nullable=False)
    frame_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    capture_ids: Mapped[str] = mapped_column(Text, nullable=False)
    decoration: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    rendered_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_delete_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    file_deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class OperationRow(Base):
    __tablename__ = "booth_operations"
    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_booth_operations_key"),
        # Recovery after a restart looks for exactly these.
        Index(
            "ix_booth_operations_pending",
            "status",
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("booth_sessions.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_boot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    result_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class DeviceOperationRow(Base):
    __tablename__ = "booth_device_operations"
    __table_args__ = (
        UniqueConstraint("device_id", "idempotency_key", name="uq_device_operations_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


def _snapshot_json(snapshot: ProfileSnapshot) -> str:
    return json.dumps(
        {
            "profile_id": snapshot.profile_id,
            "profile_revision": snapshot.profile_revision,
            "countdown_seconds": snapshot.countdown_seconds,
            "mirror": snapshot.mirror,
            "retake_mode": str(snapshot.retake_mode),
            "delivery_mode": snapshot.delivery_mode,
            "inactivity_timeout_s": snapshot.inactivity_timeout_s,
            "layouts": [
                {
                    "template_key": layout.template_key,
                    "template_version": layout.template_version,
                    "layout_label": layout.layout_label,
                    "frame_id": layout.frame_id,
                    "frame_sha256": layout.frame_sha256,
                    "captures": layout.captures,
                    "outputs": layout.outputs,
                }
                for layout in snapshot.layouts
            ],
        },
        separators=(",", ":"),
    )


def _snapshot_of(raw: str) -> ProfileSnapshot:
    data: dict[str, Any] = json.loads(raw)
    return ProfileSnapshot(
        profile_id=str(data["profile_id"]),
        profile_revision=int(data["profile_revision"]),
        countdown_seconds=int(data["countdown_seconds"]),
        mirror=bool(data["mirror"]),
        retake_mode=RetakeMode(str(data["retake_mode"])),
        delivery_mode=str(data["delivery_mode"]),
        inactivity_timeout_s=int(data["inactivity_timeout_s"]),
        layouts=tuple(
            LayoutOffer(
                template_key=str(entry["template_key"]),
                template_version=int(entry["template_version"]),
                layout_label=str(entry["layout_label"]),
                frame_id=str(entry["frame_id"]),
                frame_sha256=str(entry["frame_sha256"]),
                captures=int(entry["captures"]),
                outputs=int(entry["outputs"]),
            )
            for entry in data["layouts"]
        ),
    )


def _selection_json(selection: Selection) -> str:
    return json.dumps(
        {
            "template_key": selection.template_key,
            "template_version": selection.template_version,
            "layout_label": selection.layout_label,
            "frame_id": selection.frame_id,
            "frame_sha256": selection.frame_sha256,
            "captures": selection.captures,
            "outputs": selection.outputs,
        },
        separators=(",", ":"),
    )


def _selection_of(raw: str | None) -> Selection | None:
    if raw is None:
        return None
    data: dict[str, Any] = json.loads(raw)
    return Selection(
        template_key=str(data["template_key"]),
        template_version=int(data["template_version"]),
        layout_label=str(data["layout_label"]),
        frame_id=str(data["frame_id"]),
        frame_sha256=str(data["frame_sha256"]),
        captures=int(data["captures"]),
        outputs=int(data["outputs"]),
    )


def _session_of(row: BoothSessionRow) -> BoothSession:
    return BoothSession(
        id=row.id,
        device_id=row.device_id,
        event_profile_id=row.event_profile_id,
        state=SessionState(row.state),
        state_version=row.state_version,
        profile=_snapshot_of(row.profile_snapshot),
        selection=_selection_of(row.selection_snapshot),
        expected_capture_count=row.expected_capture_count,
        successful_capture_count=row.successful_capture_count,
        failed_capture_attempts=row.failed_capture_attempts,
        started_at=row.started_at,
        last_activity_at=row.last_activity_at,
        completed_at=row.completed_at,
        error_code=row.error_code,
        eligibility=json.loads(row.eligibility_result) if row.eligibility_result else None,
        is_test=row.is_test,
    )


def _capture_of(row: CaptureAssetRow) -> CaptureAsset:
    return CaptureAsset(
        id=row.id,
        session_id=row.session_id,
        operation_id=row.operation_id,
        shot_index=row.shot_index,
        attempt_no=row.attempt_no,
        idempotency_key=row.idempotency_key,
        status=CaptureStatus(row.status),
        storage_key=row.storage_key,
        sha256=row.sha256,
        width=row.width,
        height=row.height,
        mirrored=row.mirrored,
        captured_at=row.captured_at,
        failure_reason=row.failure_reason,
    )


def _output_of(row: OutputAssetRow) -> OutputAsset:
    return OutputAsset(
        id=row.id,
        session_id=row.session_id,
        operation_id=row.operation_id,
        output_index=row.output_index,
        status=OutputStatus(row.status),
        render_fingerprint=row.render_fingerprint,
        template_key=row.template_key,
        template_version=row.template_version,
        frame_id=row.frame_id,
        frame_sha256=row.frame_sha256,
        capture_ids=tuple(json.loads(row.capture_ids)),
        storage_key=row.storage_key,
        sha256=row.sha256,
        width=row.width,
        height=row.height,
        byte_size=row.byte_size,
        rendered_at=row.rendered_at,
        decoration=row.decoration,
        failure_reason=row.failure_reason,
    )


def _operation_of(row: OperationRow) -> Operation:
    return Operation(
        id=row.id,
        session_id=row.session_id,
        idempotency_key=row.idempotency_key,
        kind=row.kind,
        fingerprint=row.fingerprint,
        status=OperationStatus(row.status),
        owner_boot_id=row.owner_boot_id,
        result_ref=row.result_ref,
        failure_code=row.failure_code,
    )


class SqlSessionRepository(SessionRepository):
    def __init__(self, engine: Engine) -> None:
        self._sessions: sessionmaker[Session] = sessionmaker(
            bind=engine, expire_on_commit=False, future=True
        )

    # ---- reading ---------------------------------------------------------------------------

    def get(self, session_id: str) -> BoothSession | None:
        with self._sessions() as db:
            row = db.get(BoothSessionRow, session_id)
            return _session_of(row) if row else None

    def active_for_device(self, device_id: str) -> BoothSession | None:
        with self._sessions() as db:
            row = db.scalars(
                select(BoothSessionRow)
                .where(
                    BoothSessionRow.device_id == device_id,
                    BoothSessionRow.state.notin_([str(state) for state in _TERMINAL]),
                )
                .order_by(BoothSessionRow.started_at.desc())
            ).first()
            return _session_of(row) if row else None

    def device_operation(self, device_id: str, key: str) -> DeviceOperation | None:
        with self._sessions() as db:
            row = db.scalars(
                select(DeviceOperationRow).where(
                    DeviceOperationRow.device_id == device_id,
                    DeviceOperationRow.idempotency_key == key,
                )
            ).first()
            if row is None:
                return None
            return DeviceOperation(
                id=row.id,
                device_id=row.device_id,
                idempotency_key=row.idempotency_key,
                fingerprint=row.fingerprint,
                status=OperationStatus(row.status),
                result_ref=row.result_ref,
            )

    def operation(self, session_id: str, key: str) -> Operation | None:
        with self._sessions() as db:
            row = db.scalars(
                select(OperationRow).where(
                    OperationRow.session_id == session_id, OperationRow.idempotency_key == key
                )
            ).first()
            return _operation_of(row) if row else None

    def capture(self, capture_id: str) -> CaptureAsset | None:
        with self._sessions() as db:
            row = db.get(CaptureAssetRow, capture_id)
            return _capture_of(row) if row else None

    def captures(self, session_id: str) -> list[CaptureAsset]:
        with self._sessions() as db:
            rows = db.scalars(
                select(CaptureAssetRow)
                .where(CaptureAssetRow.session_id == session_id)
                .order_by(CaptureAssetRow.shot_index, CaptureAssetRow.attempt_no)
            ).all()
            return [_capture_of(row) for row in rows]

    # ---- writing ---------------------------------------------------------------------------

    def create(self, session: BoothSession, operation: DeviceOperation) -> BoothSession:
        with self._sessions() as db, db.begin():
            # One visit per device: whatever that device left unfinished ends here. A visit whose
            # photos were already delivered is complete (its guest's link keeps working); any
            # other is abandoned.
            db.execute(
                update(BoothSessionRow)
                .where(
                    BoothSessionRow.device_id == session.device_id,
                    BoothSessionRow.state == str(SessionState.DELIVERED),
                )
                .values(
                    state=str(SessionState.COMPLETED),
                    state_version=BoothSessionRow.state_version + 1,
                    completed_at=session.started_at,
                    error_code="next_guest",
                )
            )
            db.execute(
                update(BoothSessionRow)
                .where(
                    BoothSessionRow.device_id == session.device_id,
                    BoothSessionRow.state.notin_([str(state) for state in _TERMINAL]),
                )
                .values(
                    state=str(SessionState.ABANDONED),
                    completed_at=session.started_at,
                    error_code="replaced",
                )
            )
            db.add(
                BoothSessionRow(
                    id=session.id,
                    device_id=session.device_id,
                    event_profile_id=session.event_profile_id,
                    state=str(session.state),
                    state_version=session.state_version,
                    profile_snapshot=_snapshot_json(session.profile),
                    selection_snapshot=None,
                    expected_capture_count=session.expected_capture_count,
                    successful_capture_count=0,
                    failed_capture_attempts=0,
                    eligibility_result=json.dumps(dict(session.eligibility or {})),
                    started_at=session.started_at,
                    last_activity_at=session.last_activity_at,
                    is_test=session.is_test,
                )
            )
            db.add(
                DeviceOperationRow(
                    id=operation.id,
                    device_id=operation.device_id,
                    idempotency_key=operation.idempotency_key,
                    fingerprint=operation.fingerprint,
                    status=str(operation.status),
                    result_ref=operation.result_ref,
                    created_at=session.started_at,
                )
            )
        return session

    def touch(self, session_id: str, at: datetime) -> None:
        with self._sessions() as db, db.begin():
            db.execute(
                update(BoothSessionRow)
                .where(
                    BoothSessionRow.id == session_id,
                    BoothSessionRow.state.notin_([str(state) for state in _TERMINAL]),
                )
                .values(last_activity_at=at)
            )

    def select_frame(
        self, session_id: str, expected_version: int, selection: Selection, at: datetime
    ) -> BoothSession:
        with self._sessions() as db, db.begin():
            row = self._locked(db, session_id)
            if row.state_version != expected_version:
                raise StaleSessionError()
            if row.selection_snapshot is not None:
                raise TransitionRefusedError("this session already has its frame")
            row.selection_snapshot = _selection_json(selection)
            row.expected_capture_count = selection.captures
            row.state = str(SessionState.CAPTURING)
            row.state_version += 1
            row.last_activity_at = at
            db.flush()
            return _session_of(row)

    def start_capture(self, capture: CaptureAsset, operation: Operation, at: datetime) -> None:
        with self._sessions() as db, db.begin():
            db.add(
                OperationRow(
                    id=operation.id,
                    session_id=operation.session_id,
                    idempotency_key=operation.idempotency_key,
                    kind=operation.kind,
                    fingerprint=operation.fingerprint,
                    status=str(OperationStatus.PENDING),
                    owner_boot_id=operation.owner_boot_id,
                    result_ref=capture.id,
                    created_at=at,
                )
            )
            db.add(
                CaptureAssetRow(
                    id=capture.id,
                    session_id=capture.session_id,
                    operation_id=capture.operation_id,
                    shot_index=capture.shot_index,
                    attempt_no=capture.attempt_no,
                    idempotency_key=capture.idempotency_key,
                    status=str(CaptureStatus.PENDING),
                    storage_key=capture.storage_key,
                    sha256=capture.sha256,
                    width=capture.width,
                    height=capture.height,
                    mirrored=capture.mirrored,
                    captured_at=capture.captured_at,
                )
            )

    def finalize_capture(self, operation_id: str, facts: CaptureFacts) -> CaptureOutcome:
        with self._sessions() as db, db.begin():
            operation = db.get(OperationRow, operation_id)
            if operation is None:
                raise SessionNotFoundError()
            capture = db.get(CaptureAssetRow, operation.result_ref or "")
            if capture is None:
                raise SessionNotFoundError()
            row = self._locked(db, operation.session_id)
            if operation.status != str(OperationStatus.PENDING):
                # Somebody already settled this one: answer with what was recorded.
                return CaptureOutcome(capture=_capture_of(capture), session=_session_of(row))

            superseded = db.scalars(
                select(CaptureAssetRow).where(
                    CaptureAssetRow.session_id == capture.session_id,
                    CaptureAssetRow.shot_index == capture.shot_index,
                    CaptureAssetRow.attempt_no > capture.attempt_no,
                )
            ).first()
            ok_already = db.scalars(
                select(CaptureAssetRow).where(
                    CaptureAssetRow.session_id == capture.session_id,
                    CaptureAssetRow.shot_index == capture.shot_index,
                    CaptureAssetRow.status == str(CaptureStatus.OK),
                    CaptureAssetRow.id != capture.id,
                )
            ).first()
            usable = (
                row.state == str(SessionState.CAPTURING)
                and superseded is None
                and ok_already is None
                and capture.sha256 == facts.sha256
            )
            if not usable:
                return self._fail(db, row, operation, capture, "superseded")

            capture.status = str(CaptureStatus.OK)
            capture.width = facts.width
            capture.height = facts.height
            operation.status = str(OperationStatus.DONE)
            operation.finished_at = capture.captured_at
            db.flush()  # the new "ok" row is counted below
            row.successful_capture_count = (
                db.scalar(
                    select(func.count())
                    .select_from(CaptureAssetRow)
                    .where(
                        CaptureAssetRow.session_id == row.id,
                        CaptureAssetRow.status == str(CaptureStatus.OK),
                    )
                )
                or 0
            )
            row.state_version += 1
            row.last_activity_at = capture.captured_at
            db.flush()
            return CaptureOutcome(capture=_capture_of(capture), session=_session_of(row))

    def fail_capture(self, operation_id: str, code: str) -> CaptureOutcome:
        with self._sessions() as db, db.begin():
            operation = db.get(OperationRow, operation_id)
            if operation is None:
                raise SessionNotFoundError()
            capture = db.get(CaptureAssetRow, operation.result_ref or "")
            if capture is None:
                raise SessionNotFoundError()
            row = self._locked(db, operation.session_id)
            if operation.status != str(OperationStatus.PENDING):
                return CaptureOutcome(capture=_capture_of(capture), session=_session_of(row))
            return self._fail(db, row, operation, capture, code)

    def allocate_retake(
        self, session_id: str, expected_version: int, shots: Sequence[int], at: datetime
    ) -> BoothSession:
        with self._sessions() as db, db.begin():
            row = self._locked(db, session_id)
            if row.state_version != expected_version:
                raise StaleSessionError()
            replaced = 0
            for shot in shots:
                current = db.scalars(
                    select(CaptureAssetRow).where(
                        CaptureAssetRow.session_id == session_id,
                        CaptureAssetRow.shot_index == shot,
                        CaptureAssetRow.status == str(CaptureStatus.OK),
                    )
                ).first()
                if current is None:
                    continue
                # The photo stops counting; its file goes once the deletion ledger is worked off.
                current.status = str(CaptureStatus.REPLACED)
                current.file_delete_pending = True
                replaced += 1
            row.successful_capture_count = max(0, row.successful_capture_count - replaced)
            row.state_version += 1
            row.last_activity_at = at
            db.flush()
            return _session_of(row)

    def finish_capturing(
        self, session_id: str, expected_version: int, at: datetime
    ) -> BoothSession:
        with self._sessions() as db, db.begin():
            row = self._locked(db, session_id)
            if row.state_version != expected_version:
                raise StaleSessionError()
            if row.successful_capture_count < row.expected_capture_count:
                raise TransitionRefusedError("some photos are still missing")
            row.state = str(SessionState.REVIEWING)
            row.state_version += 1
            row.last_activity_at = at
            db.flush()
            return _session_of(row)

    def close(
        self,
        session_id: str,
        state: SessionState,
        at: datetime,
        code: str | None = None,
        idle_since: datetime | None = None,
    ) -> BoothSession | None:
        """`idle_since` closes the visit only while nobody has touched it since that moment."""
        with self._sessions() as db, db.begin():
            row = db.get(BoothSessionRow, session_id)
            if row is None:
                return None
            if row.state in {str(terminal) for terminal in _TERMINAL}:
                return _session_of(row)
            if idle_since is not None and row.last_activity_at > idle_since:
                return _session_of(row)  # somebody is at the booth after all
            if state is SessionState.ABANDONED:
                # A visit whose photos were delivered was not abandoned: it is complete.
                state = closing_state(SessionState(row.state))
            row.state = str(state)
            row.state_version += 1
            row.completed_at = at
            row.error_code = code
            # Photos of a session nobody finished are of no use to anyone.
            for capture in db.scalars(
                select(CaptureAssetRow).where(
                    CaptureAssetRow.session_id == session_id,
                    CaptureAssetRow.status == str(CaptureStatus.PENDING),
                )
            ).all():
                capture.status = str(CaptureStatus.FAILED)
                capture.failure_reason = "session_closed"
                capture.file_delete_pending = True
            # Finished photos still being made when the visit ended will never be delivered.
            for output in db.scalars(
                select(OutputAssetRow).where(
                    OutputAssetRow.session_id == session_id,
                    OutputAssetRow.status == str(OutputStatus.PENDING),
                )
            ).all():
                output.status = str(OutputStatus.FAILED)
                output.failure_reason = "session_closed"
                output.file_delete_pending = output.storage_key is not None
            db.flush()
            return _session_of(row)

    def inactive_sessions(self, now: datetime) -> list[tuple[str, datetime]]:
        with self._sessions() as db:
            rows = db.scalars(
                select(BoothSessionRow).where(
                    BoothSessionRow.state.notin_([str(state) for state in _TERMINAL])
                )
            ).all()
            # The activity seen here is carried into the closing transaction, so a visit that
            # was used in the meantime is never ended behind the participant's back (P67-008).
            return [
                (row.id, row.last_activity_at)
                for row in rows
                if (now - row.last_activity_at).total_seconds()
                >= _snapshot_of(row.profile_snapshot).inactivity_timeout_s
            ]

    def pending_operations(self, session_id: str) -> list[Operation]:
        with self._sessions() as db:
            rows = db.scalars(
                select(OperationRow).where(
                    OperationRow.session_id == session_id,
                    OperationRow.status == str(OperationStatus.PENDING),
                )
            ).all()
            return [_operation_of(row) for row in rows]

    def session_files(self, session_id: str) -> list[str]:
        with self._sessions() as db:
            keys = [
                *db.scalars(
                    select(CaptureAssetRow.storage_key).where(
                        CaptureAssetRow.session_id == session_id
                    )
                ).all(),
                *db.scalars(
                    select(OutputAssetRow.storage_key).where(
                        OutputAssetRow.session_id == session_id
                    )
                ).all(),
            ]
            return [key for key in keys if key]

    def finished_test_sessions(self, before: datetime) -> list[str]:
        """Test visits that are over, or were left behind, and may be cleared away."""
        with self._sessions() as db:
            rows = db.scalars(
                select(BoothSessionRow).where(BoothSessionRow.is_test.is_(True))
            ).all()
            return [
                row.id
                for row in rows
                if row.state in {str(state) for state in _TERMINAL} or row.last_activity_at < before
            ]

    def forget_test_session(self, session_id: str) -> list[str]:
        """Remove one test visit with its photos and operations; a guest's visit is never taken."""
        with self._sessions() as db, db.begin():
            row = db.get(BoothSessionRow, session_id)
            if row is None or not row.is_test:
                return []  # never a real booth visit
            keys = [
                *db.scalars(
                    select(CaptureAssetRow.storage_key).where(
                        CaptureAssetRow.session_id == session_id
                    )
                ).all(),
                *db.scalars(
                    select(OutputAssetRow.storage_key).where(
                        OutputAssetRow.session_id == session_id
                    )
                ).all(),
            ]
            # Plain DELETEs, children first: the session's own foreign keys cascade anyway (the
            # delivery module's link rows included), so deleting each child through the identity
            # map would only look for rows already gone.
            db.execute(delete(OperationRow).where(OperationRow.session_id == session_id))
            db.execute(delete(CaptureAssetRow).where(CaptureAssetRow.session_id == session_id))
            db.execute(delete(OutputAssetRow).where(OutputAssetRow.session_id == session_id))
            db.execute(delete(BoothSessionRow).where(BoothSessionRow.id == session_id))
            return [key for key in keys if key]

    def pinned_frames(self) -> set[str]:
        """Frames a visit in progress depends on: its own and every one its event offered."""
        pinned: set[str] = set()
        with self._sessions() as db:
            rows = db.scalars(
                select(BoothSessionRow).where(
                    BoothSessionRow.state.notin_([str(state) for state in _TERMINAL])
                )
            ).all()
        for row in rows:
            for layout in _snapshot_of(row.profile_snapshot).layouts:
                pinned.add(layout.frame_id)
            selection = _selection_of(row.selection_snapshot)
            if selection is not None:
                pinned.add(selection.frame_id)
        return pinned

    def visits(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        profile_id: str | None = None,
        states: Sequence[str] = (),
        session_id: str | None = None,
    ) -> list[VisitFacts]:
        """Guests' visits, newest first, with what they made. Organizer tests never appear."""
        query = select(BoothSessionRow).where(BoothSessionRow.is_test.is_(False))
        if session_id is not None:
            query = query.where(BoothSessionRow.id == session_id)
        if since is not None:
            query = query.where(BoothSessionRow.started_at >= since)
        if until is not None:
            query = query.where(BoothSessionRow.started_at < until)
        if profile_id is not None:
            query = query.where(BoothSessionRow.event_profile_id == profile_id)
        if states:
            query = query.where(BoothSessionRow.state.in_(list(states)))
        query = query.order_by(BoothSessionRow.started_at.desc(), BoothSessionRow.id.desc())
        retakes: dict[str, int] = {}
        outputs: dict[str, int] = {}
        made_at: dict[str, datetime] = {}
        decorations: dict[str, str | None] = {}
        with self._sessions() as db:
            rows = db.scalars(query).all()
            ids = [row.id for row in rows]
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                # A retake is a good photo taken again: every good photo of a shot after its
                # first. A failed upload tried again is not one (P10-R3).
                for sid, _shot, count in db.execute(
                    select(
                        CaptureAssetRow.session_id, CaptureAssetRow.shot_index, func.count()
                    )
                    .where(
                        CaptureAssetRow.session_id.in_(chunk),
                        CaptureAssetRow.status.in_(
                            [str(CaptureStatus.OK), str(CaptureStatus.REPLACED)]
                        ),
                    )
                    .group_by(CaptureAssetRow.session_id, CaptureAssetRow.shot_index)
                ).all():
                    retakes[sid] = retakes.get(sid, 0) + max(0, int(count) - 1)
                for output in db.scalars(
                    select(OutputAssetRow).where(
                        OutputAssetRow.session_id.in_(chunk),
                        OutputAssetRow.status == str(OutputStatus.OK),
                    )
                ).all():
                    sid = output.session_id
                    outputs[sid] = outputs.get(sid, 0) + 1
                    decorations.setdefault(sid, output.decoration)
                    if sid not in made_at or output.rendered_at < made_at[sid]:
                        made_at[sid] = output.rendered_at
        facts: list[VisitFacts] = []
        for row in rows:
            selection = _selection_of(row.selection_snapshot)
            facts.append(
                VisitFacts(
                    id=row.id,
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                    photos_made_at=made_at.get(row.id),
                    state=SessionState(row.state),
                    error_code=row.error_code,
                    profile_id=row.event_profile_id,
                    template_key=selection.template_key if selection else None,
                    photos=row.successful_capture_count,
                    failed_attempts=row.failed_capture_attempts,
                    retakes=retakes.get(row.id, 0),
                    outputs=outputs.get(row.id, 0),
                    decoration=decorations.get(row.id),
                )
            )
        return facts

    def unfinished_operations(self, boot_id: str) -> list[Operation]:
        with self._sessions() as db:
            rows = db.scalars(
                select(OperationRow).where(
                    OperationRow.status == str(OperationStatus.PENDING),
                    OperationRow.owner_boot_id != boot_id,
                )
            ).all()
            return [_operation_of(row) for row in rows]

    def files_to_delete(self) -> list[tuple[str, str]]:
        with self._sessions() as db:
            rows = db.scalars(
                select(CaptureAssetRow).where(
                    CaptureAssetRow.file_delete_pending.is_(True),
                    CaptureAssetRow.storage_key.is_not(None),
                )
            ).all()
            return [(row.id, row.storage_key or "") for row in rows]

    def mark_file_deleted(self, capture_id: str, at: datetime) -> None:
        with self._sessions() as db, db.begin():
            row = db.get(CaptureAssetRow, capture_id)
            if row is None:
                return
            row.file_delete_pending = False
            row.file_deleted_at = at

    # ---- finished photos ---------------------------------------------------------------------

    def output(self, output_id: str) -> OutputAsset | None:
        with self._sessions() as db:
            row = db.get(OutputAssetRow, output_id)
            return _output_of(row) if row else None

    def outputs(self, session_id: str) -> list[OutputAsset]:
        with self._sessions() as db:
            rows = db.scalars(
                select(OutputAssetRow)
                .where(OutputAssetRow.session_id == session_id)
                .order_by(OutputAssetRow.output_index, OutputAssetRow.rendered_at)
            ).all()
            return [_output_of(row) for row in rows]

    def start_render(
        self, operation: Operation, outputs: Sequence[OutputAsset], at: datetime
    ) -> None:
        with self._sessions() as db, db.begin():
            db.add(
                OperationRow(
                    id=operation.id,
                    session_id=operation.session_id,
                    idempotency_key=operation.idempotency_key,
                    kind=operation.kind,
                    fingerprint=operation.fingerprint,
                    status=str(OperationStatus.PENDING),
                    owner_boot_id=operation.owner_boot_id,
                    result_ref=None,
                    created_at=at,
                )
            )
            for output in outputs:
                db.add(
                    OutputAssetRow(
                        id=output.id,
                        session_id=output.session_id,
                        operation_id=output.operation_id,
                        output_index=output.output_index,
                        status=str(OutputStatus.PENDING),
                        render_fingerprint=output.render_fingerprint,
                        template_key=output.template_key,
                        template_version=output.template_version,
                        frame_id=output.frame_id,
                        frame_sha256=output.frame_sha256,
                        capture_ids=json.dumps(list(output.capture_ids)),
                        decoration=output.decoration,
                        storage_key=output.storage_key,
                        sha256=output.sha256,
                        width=output.width,
                        height=output.height,
                        byte_size=output.byte_size,
                        rendered_at=output.rendered_at,
                    )
                )

    def finalize_render(self, operation_id: str, fingerprint: str) -> RenderOutcome:
        with self._sessions() as db, db.begin():
            operation = db.get(OperationRow, operation_id)
            if operation is None:
                raise SessionNotFoundError()
            row = self._locked(db, operation.session_id)
            mine = self._operation_outputs(db, operation_id)
            if operation.status != str(OperationStatus.PENDING):
                # Somebody already settled this one: answer with what was recorded.
                return RenderOutcome(
                    session=_session_of(row), outputs=tuple(_output_of(o) for o in mine)
                )
            usable = (
                row.state == str(SessionState.REVIEWING)
                and bool(mine)
                and all(o.render_fingerprint == fingerprint and o.sha256 for o in mine)
            )
            if not usable:
                return self._fail_render(db, row, operation, mine, "superseded")
            for output in mine:
                # A finished photo made earlier from other inputs stops counting.
                for older in db.scalars(
                    select(OutputAssetRow).where(
                        OutputAssetRow.session_id == row.id,
                        OutputAssetRow.output_index == output.output_index,
                        OutputAssetRow.status == str(OutputStatus.OK),
                        OutputAssetRow.id != output.id,
                    )
                ).all():
                    older.status = str(OutputStatus.SUPERSEDED)
                    older.file_delete_pending = older.storage_key is not None
                db.flush()
                output.status = str(OutputStatus.OK)
            operation.status = str(OperationStatus.DONE)
            operation.finished_at = mine[0].rendered_at
            row.state = str(SessionState.DELIVERED)
            row.state_version += 1
            row.last_activity_at = mine[0].rendered_at
            db.flush()
            return RenderOutcome(
                session=_session_of(row), outputs=tuple(_output_of(o) for o in mine)
            )

    def fail_render(self, operation_id: str, code: str) -> RenderOutcome:
        with self._sessions() as db, db.begin():
            operation = db.get(OperationRow, operation_id)
            if operation is None:
                raise SessionNotFoundError()
            row = self._locked(db, operation.session_id)
            mine = self._operation_outputs(db, operation_id)
            if operation.status != str(OperationStatus.PENDING):
                return RenderOutcome(
                    session=_session_of(row), outputs=tuple(_output_of(o) for o in mine)
                )
            return self._fail_render(db, row, operation, mine, code)

    def output_files_to_delete(self) -> list[tuple[str, str]]:
        with self._sessions() as db:
            rows = db.scalars(
                select(OutputAssetRow).where(
                    OutputAssetRow.file_delete_pending.is_(True),
                    OutputAssetRow.storage_key.is_not(None),
                )
            ).all()
            return [(row.id, row.storage_key or "") for row in rows]

    def mark_output_file_deleted(self, output_id: str, at: datetime) -> None:
        with self._sessions() as db, db.begin():
            row = db.get(OutputAssetRow, output_id)
            if row is None:
                return
            row.file_delete_pending = False
            row.file_deleted_at = at

    # ---- helpers ---------------------------------------------------------------------------

    def _operation_outputs(self, db: Session, operation_id: str) -> list[OutputAssetRow]:
        return list(
            db.scalars(
                select(OutputAssetRow)
                .where(OutputAssetRow.operation_id == operation_id)
                .order_by(OutputAssetRow.output_index)
            ).all()
        )

    def _fail_render(
        self,
        db: Session,
        row: BoothSessionRow,
        operation: OperationRow,
        outputs: Sequence[OutputAssetRow],
        code: str,
    ) -> RenderOutcome:
        for output in outputs:
            output.status = str(OutputStatus.FAILED)
            output.failure_reason = code
            output.file_delete_pending = output.storage_key is not None
        operation.status = str(OperationStatus.FAILED)
        operation.failure_code = code
        operation.finished_at = outputs[0].rendered_at if outputs else operation.created_at
        db.flush()
        return RenderOutcome(
            session=_session_of(row), outputs=tuple(_output_of(o) for o in outputs)
        )

    def _locked(self, db: Session, session_id: str) -> BoothSessionRow:
        row = db.get(BoothSessionRow, session_id, with_for_update=False)
        if row is None:
            raise SessionNotFoundError()
        return row

    def _fail(
        self,
        db: Session,
        row: BoothSessionRow,
        operation: OperationRow,
        capture: CaptureAssetRow,
        code: str,
    ) -> CaptureOutcome:
        capture.status = str(CaptureStatus.FAILED)
        capture.failure_reason = code
        capture.file_delete_pending = capture.storage_key is not None
        operation.status = str(OperationStatus.FAILED)
        operation.failure_code = code
        operation.finished_at = capture.captured_at
        row.failed_capture_attempts += 1
        db.flush()
        return CaptureOutcome(capture=_capture_of(capture), session=_session_of(row))


_TERMINAL = (
    SessionState.COMPLETED,
    SessionState.CANCELLED,
    SessionState.ERROR,
    SessionState.ABANDONED,
)
