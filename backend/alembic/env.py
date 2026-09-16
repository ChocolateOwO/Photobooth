"""Alembic environment. The database URL must be supplied by photobooth's Migrator."""

from __future__ import annotations

from alembic import context
from sqlalchemy import URL, event
from sqlalchemy.engine import Engine, create_engine

from photobooth.core.db import Base

config = context.config
target_metadata = Base.metadata


def _url() -> URL:
    url = config.attributes.get("photobooth_db_url")
    if not isinstance(url, URL):
        raise RuntimeError("Run migrations through photobooth.core.migrations.Migrator")
    return url


def _foreign_keys_on(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine: Engine = create_engine(_url())
    event.listen(engine, "connect", _foreign_keys_on)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, render_as_batch=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
