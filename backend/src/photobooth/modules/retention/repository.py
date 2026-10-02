"""SQLAlchemy RetentionRepository: the booth's one policy row and the record of cleanups."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Engine, Integer, String, Text, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from photobooth.core.db import Base, UtcDateTime
from photobooth.modules.retention.domain import (
    MetadataMode,
    RetentionError,
    RetentionPolicy,
    RetentionRepository,
    RetentionRun,
    Trigger,
)

POLICY_ID = 1


class RetentionPolicyRow(Base):
    __tablename__ = "retention_policy"
    __table_args__ = (CheckConstraint("id = 1", name="ck_retention_policy_single"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    originals_days: Mapped[int] = mapped_column(Integer, nullable=False)
    outputs_days: Mapped[int] = mapped_column(Integer, nullable=False)
    link_days: Mapped[int] = mapped_column(Integer, nullable=False)
    temp_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_days: Mapped[int] = mapped_column(Integer, nullable=False)
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


def _policy_of(row: RetentionPolicyRow) -> RetentionPolicy:
    return RetentionPolicy(
        originals_days=row.originals_days,
        outputs_days=row.outputs_days,
        link_days=row.link_days,
        temp_hours=row.temp_hours,
        metadata_mode=MetadataMode(row.metadata_mode),
        metadata_days=row.metadata_days,
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

    def policy(self) -> RetentionPolicy:
        with self._sessions() as db:
            row = db.get(RetentionPolicyRow, POLICY_ID)
            return _policy_of(row) if row else RetentionPolicy()

    def save_policy(
        self, policy: RetentionPolicy, expected_revision: int, at: datetime
    ) -> RetentionPolicy:
        values = {
            "originals_days": policy.originals_days,
            "outputs_days": policy.outputs_days,
            "link_days": policy.link_days,
            "temp_hours": policy.temp_hours,
            "metadata_mode": policy.metadata_mode.value,
            "metadata_days": policy.metadata_days,
            "activity_log_days": policy.activity_log_days,
            "backup_days": policy.backup_days,
            "app_log_days": policy.app_log_days,
            "revision": expected_revision + 1,
            "updated_at": at,
        }
        with self._sessions() as db, db.begin():
            result = db.execute(
                update(RetentionPolicyRow)
                .where(
                    RetentionPolicyRow.id == POLICY_ID,
                    RetentionPolicyRow.revision == expected_revision,
                )
                .values(**values)
            )
            if not getattr(result, "rowcount", 0):
                raise RetentionError("the policy was changed meanwhile; reload it and try again")
            row = db.get(RetentionPolicyRow, POLICY_ID)
            assert row is not None
            db.flush()
            return _policy_of(row)

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
            return [
                RetentionRun(
                    id=row.id,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                    dry_run=row.dry_run,
                    trigger=Trigger(row.trigger),
                    counts=json.loads(row.counts),
                    errors=tuple(json.loads(row.errors)),
                )
                for row in rows
            ]

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
