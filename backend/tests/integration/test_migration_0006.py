"""Migration 0006: offered frames become photo sizes; the countdown may be 1-10 seconds."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from photobooth.core.db import create_sqlite_engine
from photobooth.core.migrations import Migrator
from photobooth.modules.event_profiles.repository import SqlEventProfileRepository
from tests.integration.test_migration_0005 import KEPT, _prepare, _tables

SIZES = {
    # p1 offered a 4x6 built-in frame and an uploaded strip; p2 (deleted) a 3x4 frame;
    # p3 a strip and a 3x4 frame (see the 0005 test data).
    "p1": ["print_4x6", "strip_2x6"],
    "p2": ["print_3x4"],
    "p3": ["print_3x4", "strip_2x6"],
}


def _sizes(conn: sqlite3.Connection) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for pid, key in conn.execute(
        "SELECT profile_id, template_key FROM event_profile_layouts ORDER BY profile_id, position"
    ):
        result.setdefault(pid, []).append(key)
    return result


def _at_0005(db: Path) -> tuple[Migrator, list[tuple[object, ...]]]:
    migrator, _before = _prepare(db)
    migrator.upgrade("0005_available_frames")
    with sqlite3.connect(db) as conn:
        before = conn.execute(f"SELECT {KEPT} FROM event_profiles ORDER BY id").fetchall()  # noqa: S608
    return migrator, before


def test_offered_frames_become_sizes_and_nothing_else_changes(thai_root: Path) -> None:
    db = thai_root / "ข้อมูล" / "p6.sqlite"
    migrator, before = _at_0005(db)
    with sqlite3.connect(db) as conn:
        frames_before = conn.execute("SELECT * FROM frame_assets ORDER BY id").fetchall()
        media_before = conn.execute("SELECT * FROM media_assets ORDER BY id").fetchall()
    migrator.upgrade("0006_photo_sizes_countdown")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert conn.execute(f"SELECT {KEPT} FROM event_profiles ORDER BY id").fetchall() == before  # noqa: S608
        assert _sizes(conn) == SIZES
        assert "event_profile_available_frames" not in _tables(conn)
        # Frames and their stored files are untouched.
        assert conn.execute("SELECT * FROM frame_assets ORDER BY id").fetchall() == frames_before
        assert conn.execute("SELECT * FROM media_assets ORDER BY id").fetchall() == media_before
        # The rebuilt table keeps its indexes and now allows 1-10 seconds only.
        indexes = {r[1] for r in conn.execute("PRAGMA index_list(event_profiles)")}
        assert {"uq_event_profiles_live_name", "uq_event_profiles_single_active"} <= indexes
        for seconds in (1, 10):
            conn.execute(
                "UPDATE event_profiles SET countdown_seconds = ? WHERE id = 'p3'", (seconds,)
            )
        for seconds in (0, 11):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE event_profiles SET countdown_seconds = ? WHERE id = 'p3'", (seconds,)
                )
        conn.rollback()
        # The size table points at the rebuilt profiles table.
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    engine = create_sqlite_engine(db)
    try:
        profiles = {p.id: p for p in SqlEventProfileRepository(engine).list_profiles(True)}
        assert profiles["p1"].is_active and profiles["p1"].settings.enabled_layouts == (
            "print_4x6",
            "strip_2x6",
        )
        assert profiles["p1"].settings.countdown_seconds == 5
        assert profiles["p1"].settings.logo_asset_id == "logo1"
        assert profiles["p2"].deleted and profiles["p2"].settings.enabled_layouts == ("print_3x4",)
    finally:
        engine.dispose()


def test_downgrade_rebuilds_the_frame_list_and_the_fixed_countdown(thai_root: Path) -> None:
    db = thai_root / "round-trip-0006.sqlite"
    migrator, before = _at_0005(db)
    migrator.upgrade("head")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE event_profiles SET countdown_seconds = 8 WHERE id = 'p1'")
    migrator.downgrade("0005_available_frames")
    with sqlite3.connect(db) as conn:
        assert "event_profile_layouts" not in _tables(conn)
        assert conn.execute("SELECT DISTINCT countdown_seconds FROM event_profiles").fetchall() == [
            (5,)
        ]
        assert conn.execute(f"SELECT {KEPT} FROM event_profiles ORDER BY id").fetchall() == before  # noqa: S608
        offered = {
            pid: {key for (key,) in conn.execute(
                "SELECT DISTINCT f.template_key FROM event_profile_available_frames a "
                "JOIN frame_assets f ON f.id = a.frame_id WHERE a.profile_id = ?", (pid,)
            )}
            for pid in SIZES
        }  # fmt: skip
        assert offered == {pid: set(keys) for pid, keys in SIZES.items()}
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE event_profiles SET countdown_seconds = 6 WHERE id = 'p1'")
    migrator.upgrade("head")
    with sqlite3.connect(db) as conn:
        assert _sizes(conn) == SIZES
