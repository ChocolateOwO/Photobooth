"""SQLAlchemy DeliveryTokenRepository.

The database keeps the invariant itself: a visit has at most one link that is not revoked
(partial unique index), so a new link and the revocation of the old one can only happen together.
Only the SHA-256 of a token is ever stored.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Engine, ForeignKey, Index, Integer, String, func, select, text, update
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from photobooth.core.db import Base, UtcDateTime
from photobooth.modules.delivery.domain import DeliveryToken, DeliveryTokenRepository, LinkFacts


class DeliveryTokenRow(Base):
    __tablename__ = "delivery_tokens"
    __table_args__ = (
        Index("uq_delivery_tokens_hash", "token_hash", unique=True),
        # One live link per visit, whatever races happen.
        Index(
            "uq_delivery_tokens_live",
            "session_id",
            unique=True,
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("booth_sessions.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def _token_of(row: DeliveryTokenRow) -> DeliveryToken:
    return DeliveryToken(
        id=row.id,
        session_id=row.session_id,
        token_hash=row.token_hash,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        opened_at=row.opened_at,
        download_count=row.download_count,
    )


class SqlDeliveryTokenRepository(DeliveryTokenRepository):
    def __init__(self, engine: Engine) -> None:
        self._sessions: sessionmaker[Session] = sessionmaker(
            bind=engine, expire_on_commit=False, future=True
        )

    def current(self, session_id: str) -> DeliveryToken | None:
        with self._sessions() as db:
            row = db.scalars(
                select(DeliveryTokenRow).where(
                    DeliveryTokenRow.session_id == session_id,
                    DeliveryTokenRow.revoked_at.is_(None),
                )
            ).first()
            return _token_of(row) if row else None

    def replace(self, token: DeliveryToken, at: datetime) -> None:
        with self._sessions() as db, db.begin():
            db.execute(
                update(DeliveryTokenRow)
                .where(
                    DeliveryTokenRow.session_id == token.session_id,
                    DeliveryTokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=at)
            )
            db.add(
                DeliveryTokenRow(
                    id=token.id,
                    session_id=token.session_id,
                    token_hash=token.token_hash,
                    created_at=token.created_at,
                    expires_at=token.expires_at,
                    download_count=0,
                )
            )

    def by_hash(self, token_hash: str) -> DeliveryToken | None:
        with self._sessions() as db:
            row = db.scalars(
                select(DeliveryTokenRow).where(DeliveryTokenRow.token_hash == token_hash)
            ).first()
            return _token_of(row) if row else None

    def mark_opened(self, token_id: str, at: datetime) -> bool:
        with self._sessions() as db, db.begin():
            result = db.execute(
                update(DeliveryTokenRow)
                .where(DeliveryTokenRow.id == token_id, DeliveryTokenRow.opened_at.is_(None))
                .values(opened_at=at)
            )
            return bool(getattr(result, "rowcount", 0))

    def facts(self, session_ids: Sequence[str]) -> dict[str, LinkFacts]:
        found: dict[str, LinkFacts] = {}
        ids = list(session_ids)
        with self._sessions() as db:
            for start in range(0, len(ids), 500):
                rows = db.execute(
                    select(
                        DeliveryTokenRow.session_id,
                        func.count(),
                        func.count(DeliveryTokenRow.opened_at),
                        func.coalesce(func.sum(DeliveryTokenRow.download_count), 0),
                    )
                    .where(DeliveryTokenRow.session_id.in_(ids[start : start + 500]))
                    .group_by(DeliveryTokenRow.session_id)
                ).all()
                for session_id, links, opened, downloads in rows:
                    found[session_id] = LinkFacts(
                        issued=links > 0, opened=opened > 0, downloads=int(downloads)
                    )
        return found

    def count_download(self, token_id: str) -> None:
        with self._sessions() as db, db.begin():
            db.execute(
                update(DeliveryTokenRow)
                .where(DeliveryTokenRow.id == token_id)
                .values(download_count=DeliveryTokenRow.download_count + 1)
            )

    def revoke_session(self, session_id: str, at: datetime) -> list[str]:
        with self._sessions() as db, db.begin():
            live = list(
                db.scalars(
                    select(DeliveryTokenRow.id).where(
                        DeliveryTokenRow.session_id == session_id,
                        DeliveryTokenRow.revoked_at.is_(None),
                    )
                ).all()
            )
            db.execute(
                update(DeliveryTokenRow).where(DeliveryTokenRow.id.in_(live)).values(revoked_at=at)
            )
            return live
