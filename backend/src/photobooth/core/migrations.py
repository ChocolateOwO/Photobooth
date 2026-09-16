"""Programmatic Alembic runner bound to one database path."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from photobooth.core.db import create_sqlite_engine, sqlite_url

BACKEND_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


class Migrator:
    """Upgrades/downgrades one SQLite database. Never guesses the target database."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _config(self) -> Config:
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        config.attributes["photobooth_db_url"] = sqlite_url(self._db_path)
        return config

    def upgrade(self, revision: str = "head") -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        command.upgrade(self._config(), revision)

    def downgrade(self, revision: str) -> None:
        command.downgrade(self._config(), revision)

    def head_revision(self) -> str | None:
        return ScriptDirectory.from_config(self._config()).get_current_head()

    def current_revision(self) -> str | None:
        if not self._db_path.exists():
            return None
        engine = create_sqlite_engine(self._db_path)
        try:
            with engine.connect() as conn:
                return MigrationContext.configure(conn).get_current_revision()
        finally:
            engine.dispose()
