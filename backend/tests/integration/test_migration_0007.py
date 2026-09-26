"""Migration 0007: booth sessions and their captures arrive; nothing else is touched."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from photobooth.core.migrations import Migrator
from tests.integration.test_migration_0005 import _prepare, _tables
from tests.integration.test_migration_0006 import _profiles


def _at_0006(db: Path) -> tuple[Migrator, list[dict[str, object]], list[tuple[object, ...]]]:
    migrator, _before = _prepare(db)
    migrator.upgrade("0006_photo_sizes_countdown")
    with sqlite3.connect(db) as conn:
        profiles = _profiles(conn)
        frames = conn.execute("SELECT * FROM frame_assets ORDER BY id").fetchall()
    return migrator, profiles, frames


def test_sessions_arrive_and_profiles_frames_and_media_stay_as_they_were(thai_root: Path) -> None:
    db = thai_root / "ข้อมูล" / "p7.sqlite"
    migrator, profiles, frames = _at_0006(db)
    with sqlite3.connect(db) as conn:
        media = conn.execute("SELECT * FROM media_assets ORDER BY id").fetchall()

    migrator.upgrade("0007_booth_sessions")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        tables = _tables(conn)
        assert {"booth_sessions", "capture_assets", "booth_operations"} <= tables
        assert "booth_device_operations" in tables
        # Everything that existed before is untouched.
        assert _profiles(conn) == profiles
        assert conn.execute("SELECT * FROM frame_assets ORDER BY id").fetchall() == frames
        assert conn.execute("SELECT * FROM media_assets ORDER BY id").fetchall() == media
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        indexes = {row[1] for row in conn.execute("PRAGMA index_list(booth_sessions)")}
        assert "uq_booth_sessions_open_device" in indexes
        shot_indexes = {row[1] for row in conn.execute("PRAGMA index_list(capture_assets)")}
        assert "uq_capture_assets_shot_ok" in shot_indexes


def test_the_database_itself_refuses_two_visits_or_two_photos_for_one_shot(
    thai_root: Path,
) -> None:
    db = thai_root / "ข้อมูล" / "p7-rules.sqlite"
    migrator, _profiles_before, _frames = _at_0006(db)
    migrator.upgrade("0007_booth_sessions")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        profile_id = conn.execute("SELECT id FROM event_profiles LIMIT 1").fetchone()[0]

        def add_session(session_id: str, state: str = "capturing") -> None:
            conn.execute(
                "INSERT INTO booth_sessions (id, device_id, event_profile_id, state, "
                "state_version, profile_snapshot, expected_capture_count, "
                "successful_capture_count, failed_capture_attempts, started_at, last_activity_at) "
                "VALUES (?, 'device-a', ?, ?, 1, '{}', 2, 0, 0, '2026-01-01', '2026-01-01')",
                (session_id, profile_id, state),
            )

        add_session("s1")
        with pytest.raises(sqlite3.IntegrityError):
            add_session("s2")  # one unfinished visit per device
        conn.execute("UPDATE booth_sessions SET state = 'abandoned' WHERE id = 's1'")
        add_session("s2")  # the device is free again

        def add_capture(capture_id: str, shot: int, attempt: int, status: str) -> None:
            conn.execute(
                "INSERT INTO capture_assets (id, session_id, operation_id, shot_index, "
                "attempt_no, idempotency_key, status, width, height, mirrored, captured_at) "
                "VALUES (?, 's2', 'op', ?, ?, ?, ?, 100, 100, 0, '2026-01-01')",
                (capture_id, shot, attempt, f"key-{capture_id}", status),
            )

        add_capture("c1", 1, 1, "ok")
        with pytest.raises(sqlite3.IntegrityError):
            add_capture("c2", 1, 2, "ok")  # only one photo per shot may count
        add_capture("c3", 1, 2, "failed")  # other attempts may exist
        with pytest.raises(sqlite3.IntegrityError):
            add_capture("c4", 1, 2, "pending")  # one row per attempt
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE booth_sessions SET successful_capture_count = 9 WHERE id = 's2'"
            )  # never more photos than the session expects
        conn.rollback()


def test_downgrade_removes_only_the_session_tables(thai_root: Path) -> None:
    db = thai_root / "ข้อมูล" / "p7-round-trip.sqlite"
    migrator, profiles, frames = _at_0006(db)
    migrator.upgrade("head")
    migrator.downgrade("0006_photo_sizes_countdown")
    with sqlite3.connect(db) as conn:
        tables = _tables(conn)
        assert (
            not {
                "booth_sessions",
                "capture_assets",
                "booth_operations",
                "booth_device_operations",
            }
            & tables
        )
        assert _profiles(conn) == profiles
        assert conn.execute("SELECT * FROM frame_assets ORDER BY id").fetchall() == frames
    migrator.upgrade("head")
    with sqlite3.connect(db) as conn:
        assert "booth_sessions" in _tables(conn)
