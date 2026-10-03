"""SQLAlchemy RetentionRepository: the named policies, the booth's housekeeping row and the
record of cleanups."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Engine,
    Index,
    Integer,
    String,
    Text,
    delete,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from photobooth.core.db import Base, UtcDateTime
from photobooth.modules.retention.domain import (
    Housekeeping,
    MetadataMode,
    PolicyNameTakenError,
    RetentionPolicy,
    RetentionRepository,
    RetentionRun,
    StaleEditError,
    Trigger,
)

HOUSEKEEPING_ID = 1


class RetentionPolicyRow(Base):
    __tablename__ = "retention_policies"
    __table_args__ = (
        CheckConstraint(
            "metadata_mode IN ('keep', 'anonymize', 'delete')", name="ck_retention_policies_mode"
        ),
        Index("uq_retention_policies_name", "name_key", unique=True),
        # Exactly one policy is where new Event Profiles start.
        Index(
            "uq_retention_policies_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    name_key: Mapped[str] = mapped_column(String(60), nullable=False)
    originals_days: Mapped[int] = mapped_column(Integer, nullable=False)
    outputs_days: Mapped[int] = mapped_column(Integer, nullable=False)
    link_days: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class HousekeepingRow(Base):
    __tablename__ = "retention_housekeeping"
    __table_args__ = (CheckConstraint("id = 1", name="ck_retention_housekeeping_single"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    temp_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    activity_log_days: Mapped[int] = mapped_column(Integer, nullable=False)
    backup_days: Mapped[int] = mapped_column(Integer, nullable=False)
    app_log_days: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class RetentionRunRow(Base):
    __tablename__ = "retention_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    finished_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    counts: Mapped[str] = mapped_column(Text, nullable=False)
    errors: Mapped[str] = mapped_column(Text, nullable=False)


def name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _run_of(row: RetentionRunRow) -> RetentionRun:
    return RetentionRun(
        id=row.id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        dry_run=row.dry_run,
        trigger=Trigger(row.trigger),
        counts=json.loads(row.counts),
        errors=tuple(json.loads(row.errors)),
    )


def _policy_of(row: RetentionPolicyRow) -> RetentionPolicy:
    return RetentionPolicy(
        id=row.id,
        name=row.name,
        originals_days=row.originals_days,
        outputs_days=row.outputs_days,
        link_days=row.link_days,
        metadata_mode=MetadataMode(row.metadata_mode),
        metadata_days=row.metadata_days,
        is_default=row.is_default,
        revision=row.revision,
        updated_at=row.updated_at,
    )


def _housekeeping_of(row: HousekeepingRow) -> Housekeeping:
    return Housekeeping(
        temp_hours=row.temp_hours,
        activity_log_days=row.activity_log_days,
        backup_days=row.backup_days,
        app_log_days=row.app_log_days,
        revision=row.revision,
        updated_at=row.updated_at,
    )


class SqlRetentionRepository(RetentionRepository):
    def __init__(self, engine: Engine) -> None:
        self._sessions: sessionmaker[Session] = sessionmaker(
            bind=engine, expire_on_commit=False, future=True
        )

    # ---- policies -------------------------------------------------------------------------------

    def policies(self) -> list[RetentionPolicy]:
        with self._sessions() as db:
            rows = db.scalars(
                select(RetentionPolicyRow).order_by(
                    RetentionPolicyRow.is_default.desc(), RetentionPolicyRow.name_key
                )
            ).all()
            return [_policy_of(row) for row in rows]

    def policy(self, policy_id: str) -> RetentionPolicy | None:
        with self._sessions() as db:
            row = db.get(RetentionPolicyRow, policy_id)
            return _policy_of(row) if row else None

    def add_policy(self, policy: RetentionPolicy, at: datetime) -> RetentionPolicy:
        row = RetentionPolicyRow(
            id=policy.id,
            name=policy.name,
            name_key=name_key(policy.name),
            originals_days=policy.originals_days,
            outputs_days=policy.outputs_days,
            link_days=policy.link_days,
            metadata_mode=policy.metadata_mode.value,
            metadata_days=policy.metadata_days,
            is_default=False,
            revision=1,
            created_at=at,
            updated_at=at,
        )
        try:
            with self._sessions() as db, db.begin():
                db.add(row)
        except IntegrityError as exc:
            raise PolicyNameTakenError() from exc
        return _policy_of(row)

    def save_policy(
        self, policy: RetentionPolicy, expected_revision: int, at: datetime
    ) -> RetentionPolicy:
        try:
            with self._sessions() as db, db.begin():
                result = db.execute(
                    update(RetentionPolicyRow)
                    .where(
                        RetentionPolicyRow.id == policy.id,
                        RetentionPolicyRow.revision == expected_revision,
                    )
                    .values(
                        name=policy.name,
                        name_key=name_key(policy.name),
                        originals_days=policy.originals_days,
                        outputs_days=policy.outputs_days,
                        link_days=policy.link_days,
                        metadata_mode=policy.metadata_mode.value,
                        metadata_days=policy.metadata_days,
                        revision=expected_revision + 1,
                        updated_at=at,
                    )
                )
                if not getattr(result, "rowcount", 0):
                    raise StaleEditError()
                row = db.get(RetentionPolicyRow, policy.id)
                assert row is not None
                db.refresh(row)
                return _policy_of(row)
        except IntegrityError as exc:
            raise PolicyNameTakenError() from exc

    def delete_policy(self, policy_id: str) -> bool:
        with self._sessions() as db, db.begin():
            result = db.execute(
                delete(RetentionPolicyRow).where(
                    RetentionPolicyRow.id == policy_id, RetentionPolicyRow.is_default.is_(False)
                )
            )
            return bool(getattr(result, "rowcount", 0))

    def make_default(self, policy_id: str, at: datetime) -> RetentionPolicy | None:
        with self._sessions() as db, db.begin():
            row = db.get(RetentionPolicyRow, policy_id)
            if row is None:
                return None
            if not row.is_default:
                # Both rows change in one transaction: there is always exactly one default.
                db.execute(
                    update(RetentionPolicyRow)
                    .where(RetentionPolicyRow.is_default.is_(True))
                    .values(is_default=False, revision=RetentionPolicyRow.revision + 1)
                )
                db.flush()
                row.is_default = True
                row.revision += 1
                row.updated_at = at
            db.flush()
            return _policy_of(row)

    # ---- housekeeping -------------------------------------------------------------------------

    def housekeeping(self) -> Housekeeping:
        with self._sessions() as db:
            row = db.get(HousekeepingRow, HOUSEKEEPING_ID)
            return _housekeeping_of(row) if row else Housekeeping()

    def save_housekeeping(
        self, housekeeping: Housekeeping, expected_revision: int, at: datetime
    ) -> Housekeeping:
        with self._sessions() as db, db.begin():
            result = db.execute(
                update(HousekeepingRow)
                .where(
                    HousekeepingRow.id == HOUSEKEEPING_ID,
                    HousekeepingRow.revision == expected_revision,
                )
                .values(
                    temp_hours=housekeeping.temp_hours,
                    activity_log_days=housekeeping.activity_log_days,
                    backup_days=housekeeping.backup_days,
                    app_log_days=housekeeping.app_log_days,
                    revision=expected_revision + 1,
                    updated_at=at,
                )
            )
            if not getattr(result, "rowcount", 0):
                raise StaleEditError()
            row = db.get(HousekeepingRow, HOUSEKEEPING_ID)
            assert row is not None
            db.refresh(row)
            return _housekeeping_of(row)

    # ---- runs ---------------------------------------------------------------------------------

    def add_run(self, run: RetentionRun) -> None:
        with self._sessions() as db, db.begin():
            db.add(
                RetentionRunRow(
                    id=run.id,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    dry_run=run.dry_run,
                    trigger=run.trigger.value,
                    counts=json.dumps(run.counts, sort_keys=True),
                    errors=json.dumps(list(run.errors)),
                )
            )

    def runs(self, limit: int) -> list[RetentionRun]:
        with self._sessions() as db:
            rows = db.scalars(
                select(RetentionRunRow)
                .order_by(RetentionRunRow.started_at.desc(), RetentionRunRow.id.desc())
                .limit(limit)
            ).all()
            return [_run_of(row) for row in rows]

    def last_cleanup(self) -> RetentionRun | None:
        with self._sessions() as db:
            row = db.scalars(
                select(RetentionRunRow)
                .where(RetentionRunRow.dry_run.is_(False))
                .order_by(RetentionRunRow.started_at.desc(), RetentionRunRow.id.desc())
                .limit(1)
            ).first()
            return _run_of(row) if row else None

    def last_automatic_run(self) -> datetime | None:
        with self._sessions() as db:
            return db.scalar(
                select(RetentionRunRow.finished_at)
                .where(
                    RetentionRunRow.dry_run.is_(False),
                    RetentionRunRow.trigger.in_([Trigger.SCHEDULE.value, Trigger.STARTUP.value]),
                )
                .order_by(RetentionRunRow.finished_at.desc())
                .limit(1)
            )
