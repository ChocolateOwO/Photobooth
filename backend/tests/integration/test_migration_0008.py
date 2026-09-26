"""Migration 0008: a visit knows whether it is the organizer's test of the booth."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from photobooth.core.migrations import Migrator
from tests.integration.test_migration_0005 import _prepare
from tests.integration.test_migration_0006 import _profiles


def _at_0007(db: Path) -> tuple[Migrator, list[dict[str, object]]]:
    migrator, _before = _prepare(db)
    migrator.upgrade("0007_booth_sessions")
    with sqlite3.connect(db) as conn:
        return migrator, _profiles(conn)


def _add_session(conn: sqlite3.Connection, session_id: str, is_test: int | None = None) -> None:
    profile_id = conn.execute("SELECT id FROM event_profiles LIMIT 1").fetchone()[0]
    columns = (
        "id, device_id, event_profile_id, state, state_version, profile_snapshot, "
        "expected_capture_count, successful_capture_count, failed_capture_attempts, "
        "started_at, last_activity_at"
    )
    values = f"'{session_id}', 'device-{session_id}', ?, 'capturing', 1, '{{}}', 1, 0, 0, "
    values += "'2026-01-01', '2026-01-01'"
    if is_test is None:
        conn.execute(f"INSERT INTO booth_sessions ({columns}) VALUES ({values})", (profile_id,))  # noqa: S608
    else:
        conn.execute(
            f"INSERT INTO booth_sessions ({columns}, is_test) VALUES ({values}, {is_test})",  # noqa: S608
            (profile_id,),
        )


def test_visits_that_existed_are_guests_and_new_ones_can_be_tests(thai_root: Path) -> None:
    db = thai_root / "ข้อมูล" / "p8.sqlite"
    migrator, profiles = _at_0007(db)
    with sqlite3.connect(db) as conn:
        _add_session(conn, "before-the-flag")
        conn.commit()

    migrator.upgrade("0008_test_sessions")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert _profiles(conn) == profiles  # profiles are untouched
        kept = conn.execute("SELECT is_test FROM booth_sessions WHERE id = 'before-the-flag'")
        assert kept.fetchone()[0] == 0  # a visit that existed is a guest's
        _add_session(conn, "organizer-test", is_test=1)
        conn.commit()
        rows = dict(conn.execute("SELECT id, is_test FROM booth_sessions").fetchall())
        assert rows == {"before-the-flag": 0, "organizer-test": 1}
        assert "ix_booth_sessions_test" in {
            row[1] for row in conn.execute("PRAGMA index_list(booth_sessions)")
        }


def test_downgrade_removes_the_test_visits_and_leaves_the_guests(thai_root: Path) -> None:
    db = thai_root / "ข้อมูล" / "p8-round-trip.sqlite"
    migrator, profiles = _at_0007(db)
    migrator.upgrade("head")
    with sqlite3.connect(db) as conn:
        _add_session(conn, "guest", is_test=0)
        _add_session(conn, "organizer-test", is_test=1)
        conn.commit()

    migrator.downgrade("0007_booth_sessions")
    with sqlite3.connect(db) as conn:
        assert [row[0] for row in conn.execute("SELECT id FROM booth_sessions")] == ["guest"]
        assert "is_test" not in {
            row[1] for row in conn.execute("PRAGMA table_info(booth_sessions)")
        }
        assert _profiles(conn) == profiles
    migrator.upgrade("head")
    with sqlite3.connect(db) as conn:
        assert [row[0] for row in conn.execute("SELECT id FROM booth_sessions")] == ["guest"]
