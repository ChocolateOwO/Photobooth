"""SQLAlchemy ActivityRepository (table `activity_log`).

A visit's records go with the visit (ON DELETE CASCADE), so clearing an organizer's test or, later,
retention deleting a visit leaves no record of it behind. An event profile that is deleted for good
leaves its records without a profile (SET NULL).
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Engine, ForeignKey, Index, String, Text, and_, delete, func, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from photobooth.core.db import Base, UtcDateTime
from photobooth.modules.activity.domain import (
    ActivityFilter,
    ActivityRecord,
    ActivityRepository,
    ActivityType,
    Actor,
    PayloadValue,
)


class ActivityRow(Base):
    __tablename__ = "activity_log"
    __table_args__ = (
        Index("ix_activity_log_at", "at", "id"),
        Index("ix_activity_log_session", "session_id", "at"),
        Index("ix_activity_log_type", "type", "at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("booth_sessions.id", ondelete="CASCADE"), nullable=True
    )
    profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("event_profiles.id", ondelete="SET NULL"), nullable=True
    )
    admin_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


def _record_of(row: ActivityRow) -> ActivityRecord:
    payload: dict[str, PayloadValue] = json.loads(row.payload or "{}")
    return ActivityRecord(
        id=row.id,
        at=row.at,
        type=ActivityType(row.type),
        actor=Actor(row.actor),
        session_id=row.session_id,
        profile_id=row.profile_id,
        admin_username=row.admin_username,
        payload=payload,
    )


class SqlActivityRepository(ActivityRepository):
    def __init__(self, engine: Engine) -> None:
        self._sessions: sessionmaker[Session] = sessionmaker(
            bind=engine, expire_on_commit=False, future=True
        )

    def add(self, record: ActivityRecord) -> None:
        with self._sessions() as db, db.begin():
            db.add(
                ActivityRow(
                    id=record.id,
                    at=record.at,
                    type=record.type.value,
                    actor=record.actor.value,
                    session_id=record.session_id,
                    profile_id=record.profile_id,
                    admin_username=record.admin_username,
                    payload=json.dumps(dict(record.payload), sort_keys=True),
                )
            )

    def search(
        self, where: ActivityFilter, limit: int, before: tuple[datetime, str] | None = None
    ) -> list[ActivityRecord]:
        query = select(ActivityRow)
        if where.types:
            query = query.where(ActivityRow.type.in_([t.value for t in where.types]))
        if where.actors:
            query = query.where(ActivityRow.actor.in_([a.value for a in where.actors]))
        if where.session_id:
            query = query.where(ActivityRow.session_id == where.session_id)
        if where.since:
            query = query.where(ActivityRow.at >= where.since)
        if where.until:
            query = query.where(ActivityRow.at < where.until)
        if before:
            at, record_id = before
            query = query.where(
                or_(ActivityRow.at < at, and_(ActivityRow.at == at, ActivityRow.id < record_id))
            )
        query = query.order_by(ActivityRow.at.desc(), ActivityRow.id.desc()).limit(limit)
        with self._sessions() as db:
            return [_record_of(row) for row in db.scalars(query).all()]

    def for_session(self, session_id: str) -> list[ActivityRecord]:
        with self._sessions() as db:
            rows = db.scalars(
                select(ActivityRow)
                .where(ActivityRow.session_id == session_id)
                .order_by(ActivityRow.at, ActivityRow.id)
            ).all()
            return [_record_of(row) for row in rows]

    def purge(self, before: datetime, dry_run: bool) -> int:
        with self._sessions() as db, db.begin():
            count = db.scalar(select(func.count()).where(ActivityRow.at < before)) or 0
            if count and not dry_run:
                db.execute(delete(ActivityRow).where(ActivityRow.at < before))
            return int(count)
