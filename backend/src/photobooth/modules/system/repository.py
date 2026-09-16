"""SQLAlchemy implementation of AppMetaRepository."""

from __future__ import annotations

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from photobooth.modules.system.domain import AppMetaRepository


class SqlAppMetaRepository(AppMetaRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, key: str) -> str | None:
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text("SELECT value FROM app_meta WHERE key = :key"), {"key": key}
                ).first()
        except SQLAlchemyError:
            return None
        return None if row is None else str(row[0])

    def set_if_absent(self, key: str, value: str) -> str:
        with self._engine.begin() as conn:
            conn.execute(
                text("INSERT OR IGNORE INTO app_meta (key, value) VALUES (:key, :value)"),
                {"key": key, "value": value},
            )
            row = conn.execute(
                text("SELECT value FROM app_meta WHERE key = :key"), {"key": key}
            ).one()
        return str(row[0])

    def ping(self) -> bool:
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM app_meta LIMIT 1"))
        except SQLAlchemyError:
            return False
        return True

    def schema_revision(self) -> str | None:
        try:
            with self._engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        except SQLAlchemyError:
            return None
        return None if row is None else str(row[0])
