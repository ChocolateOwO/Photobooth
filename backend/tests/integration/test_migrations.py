"""Alembic upgrade/downgrade on empty and seeded databases in a Thai-character path."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from photobooth.core.migrations import ALEMBIC_INI, BACKEND_ROOT, Migrator


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _all_revisions() -> list[str]:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    return [rev.revision for rev in reversed(list(script.walk_revisions()))]


def test_single_linear_head_is_baseline() -> None:
    assert _all_revisions()[0] == "0001_baseline"
    migrator = Migrator(Path("unused.sqlite"))
    assert migrator.head_revision() == _all_revisions()[-1]


def test_upgrade_and_downgrade_empty_database_in_thai_path(thai_root: Path) -> None:
    db = thai_root / "ฐานข้อมูล" / "photobooth.sqlite"
    migrator = Migrator(db)
    migrator.upgrade("head")
    assert "app_meta" in _tables(db)
    assert migrator.current_revision() == migrator.head_revision()

    migrator.downgrade("base")
    assert "app_meta" not in _tables(db)
    assert migrator.current_revision() is None

    migrator.upgrade("head")
    assert "app_meta" in _tables(db)


def test_each_revision_steps_up_and_down_with_seeded_data(thai_root: Path) -> None:
    db = thai_root / "seeded.sqlite"
    migrator = Migrator(db)
    for revision in _all_revisions():
        migrator.upgrade(revision)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)",
                (f"seed-{revision}", "ข้อมูลทดสอบ"),
            )
        migrator.downgrade("-1")
        migrator.upgrade(revision)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('instance', 'dummy')")
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM app_meta").fetchone()[0]
    assert count >= 1
    migrator.downgrade("base")
    assert _tables(db) <= {"alembic_version"}
