"""A database stamped for another instance is never migrated, in either direction."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from photobooth.cli import main
from photobooth.core.migrations import Migrator


def _init_env(root: Path) -> Path:
    env = root / "config" / "photobooth.env"
    args = [
        "init-env", "--instance", "dummy", "--profile", "test", "--instance-root", str(root),
        "--output", str(env), "--kiosk-port", "18111", "--delivery-port", "18113",
        "--delivery-host", "127.0.0.1",
    ]  # fmt: skip
    assert main(args) == 0
    return env


def _schema_and_rows(db: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    with sqlite3.connect(db) as conn:
        schema = conn.execute("SELECT type, name FROM sqlite_master ORDER BY name").fetchall()
        rows = conn.execute("SELECT key, value FROM app_meta ORDER BY key").fetchall()
    return schema, rows


def test_foreign_database_is_never_migrated_in_either_direction(thai_root: Path) -> None:
    env = _init_env(thai_root)
    assert main(["db-upgrade", "--env-file", str(env)]) == 0
    db = thai_root / "data" / "db" / "photobooth.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE app_meta SET value='main' WHERE key='instance'")
        conn.execute("INSERT INTO app_meta (key, value) VALUES ('main-data', 'keep')")
    before = _schema_and_rows(db)

    assert main(["db-downgrade", "--env-file", str(env), "--revision", "base"]) == 2
    assert _schema_and_rows(db) == before
    assert main(["db-upgrade", "--env-file", str(env)]) == 2
    assert _schema_and_rows(db) == before


def test_downgrade_refuses_unstamped_database(thai_root: Path) -> None:
    env = _init_env(thai_root)
    db = thai_root / "data" / "db" / "photobooth.sqlite"
    Migrator(db).upgrade("head")  # schema present, no instance stamp
    assert main(["db-downgrade", "--env-file", str(env), "--revision", "base"]) == 2
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='app_meta'").fetchone()


def test_upgrade_does_not_create_database_file_for_check(thai_root: Path) -> None:
    env = _init_env(thai_root)
    db = thai_root / "data" / "db" / "photobooth.sqlite"
    assert main(["db-downgrade", "--env-file", str(env), "--revision", "base"]) == 2
    assert not db.exists()


def test_downgrade_allowed_for_own_stamped_database(thai_root: Path) -> None:
    env = _init_env(thai_root)
    assert main(["db-upgrade", "--env-file", str(env)]) == 0
    assert main(["db-downgrade", "--env-file", str(env), "--revision", "base"]) == 0
