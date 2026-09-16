"""SQLite engine factory (WAL, foreign keys) with Thai-path-safe URLs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM tables."""


def sqlite_url(db_path: Path) -> URL:
    """Build the URL without string formatting so non-ASCII paths stay intact."""
    return URL.create("sqlite+pysqlite", database=str(db_path))


def _apply_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def create_sqlite_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(sqlite_url(db_path), future=True)
    event.listen(engine, "connect", _apply_pragmas)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
