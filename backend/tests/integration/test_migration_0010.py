"""Migration 0010: the activity log arrives; nothing that existed is changed."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from photobooth.core.migrations import Migrator
from tests.integration.test_migration_0005 import _prepare, _tables
from tests.integration.test_migration_0006 import _profiles
from tests.integration.test_migration_0008 import _add_session


def _at_0009(db: Path) -> tuple[Migrator, list[dict[str, object]]]:
    migrator, _before = _prepare(db)
    migrator.upgrade("0009_outputs_delivery")
    with sqlite3.connect(db) as conn:
        return migrator, _profiles(conn)


def _add_record(conn: sqlite3.Connection, record_id: str, session_id: str | None) -> None:
    profile = conn.execute("SELECT id FROM event_profiles LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO activity_log (id, at, type, actor, session_id, profile_id, payload) "
        "VALUES (?, '2026-10-02 10:00:00', 'capture_ok', 'booth', ?, ?, '{}')",
        (record_id, session_id, profile),
    )


def test_the_activity_log_arrives_and_everything_else_stays(thai_root: Path) -> None:
    db = thai_root / "บันทึก" / "p10.sqlite"
    migrator, profiles = _at_0009(db)
    with sqlite3.connect(db) as conn:
        _add_session(conn, "earlier-visit")
        before = conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall()
        conn.commit()

    migrator.upgrade("0010_activity_log")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert "activity_log" in _tables(conn)
        assert _profiles(conn) == profiles
        assert conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall() == before
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone() == (0,)

    migrator.downgrade("0009_outputs_delivery")
    with sqlite3.connect(db) as conn:
        assert "activity_log" not in _tables(conn)
        assert _profiles(conn) == profiles
        assert conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall() == before


def test_a_visits_records_go_with_the_visit(thai_root: Path) -> None:
    db = thai_root / "บันทึก" / "p10-cascade.sqlite"
    migrator, _profiles_before = _at_0009(db)
    migrator.upgrade("head")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        _add_session(conn, "visit")
        _add_record(conn, "of-the-visit", "visit")
        _add_record(conn, "of-admin", None)
        conn.execute("DELETE FROM booth_sessions WHERE id = 'visit'")
        left = [row[0] for row in conn.execute("SELECT id FROM activity_log")]
        assert left == ["of-admin"]


def test_only_the_four_actors_are_accepted(thai_root: Path) -> None:
    db = thai_root / "บันทึก" / "p10-actor.sqlite"
    migrator, _profiles_before = _at_0009(db)
    migrator.upgrade("head")
    with sqlite3.connect(db) as conn:
        try:
            conn.execute(
                "INSERT INTO activity_log (id, at, type, actor, payload) "
                "VALUES ('x', '2026-10-02', 'admin_login', 'somebody', '{}')"
            )
        except sqlite3.IntegrityError:
            return
        raise AssertionError("an unknown actor was accepted")
