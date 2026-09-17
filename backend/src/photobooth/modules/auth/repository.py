"""SQLAlchemy AdminUserRepository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine, String, select, update
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from photobooth.core.db import Base, UtcDateTime
from photobooth.modules.auth.domain import AdminUser, AdminUserRepository


class AdminUserRow(Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    def to_domain(self) -> AdminUser:
        return AdminUser(
            id=self.id,
            username=self.username,
            password_hash=self.password_hash,
            created_at=self.created_at,
            updated_at=self.updated_at,
            last_login_at=self.last_login_at,
        )


class SqlAdminUserRepository(AdminUserRepository):
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def get_by_username(self, username: str) -> AdminUser | None:
        with self._sessions() as session:
            row = session.scalars(
                select(AdminUserRow).where(AdminUserRow.username == username)
            ).first()
            return None if row is None else row.to_domain()

    def upsert_password(self, user: AdminUser) -> AdminUser:
        with self._sessions.begin() as session:
            row = session.scalars(
                select(AdminUserRow).where(AdminUserRow.username == user.username)
            ).first()
            if row is None:
                row = AdminUserRow(
                    id=user.id,
                    username=user.username,
                    password_hash=user.password_hash,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                    last_login_at=None,
                )
                session.add(row)
            else:
                row.password_hash = user.password_hash
                row.updated_at = user.updated_at
            session.flush()
            return row.to_domain()

    def record_login(self, user_id: str, at: datetime, password_hash: str | None) -> None:
        values: dict[str, object] = {"last_login_at": at}
        if password_hash is not None:
            values["password_hash"] = password_hash
            values["updated_at"] = at
        with self._sessions.begin() as session:
            session.execute(update(AdminUserRow).where(AdminUserRow.id == user_id).values(**values))
