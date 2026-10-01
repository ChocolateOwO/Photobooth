"""Migration 0009: finished photos and take-home links arrive; nothing that existed is changed."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from photobooth.core.migrations import Migrator
from tests.integration.test_migration_0005 import _prepare, _tables
from tests.integration.test_migration_0006 import _profiles
from tests.integration.test_migration_0008 import _add_session


def _at_0008(db: Path) -> tuple[Migrator, list[dict[str, object]]]:
    migrator, _before = _prepare(db)
    migrator.upgrade("0008_test_sessions")
    with sqlite3.connect(db) as conn:
        return migrator, _profiles(conn)


def _add_output(conn: sqlite3.Connection, output_id: str, session_id: str, status: str) -> None:
    conn.execute(
        "INSERT INTO output_assets (id, session_id, operation_id, output_index, status, "
        "render_fingerprint, template_key, template_version, frame_id, frame_sha256, "
        "capture_ids, width, height, byte_size, rendered_at) "
        "VALUES (?, ?, 'op', 1, ?, 'fp', 'print_3x4', 1, 'frame', 'sha', '[]', 900, 1200, 10, "
        "'2026-01-01')",
        (output_id, session_id, status),
    )


def test_outputs_and_links_arrive_and_visits_stay_as_they_were(thai_root: Path) -> None:
    db = thai_root / "เธเนเธญเธกเธนเธฅ" / "p9.sqlite"
    migrator, profiles = _at_0008(db)
    with sqlite3.connect(db) as conn:
        _add_session(conn, "earlier-visit")
        before = conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall()
        conn.commit()

    migrator.upgrade("0009_outputs_delivery")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert {"output_assets", "delivery_tokens"} <= _tables(conn)
        assert _profiles(conn) == profiles
        assert conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall() == before
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_the_database_allows_one_counted_photo_per_output_and_one_live_link(
    thai_root: Path,
) -> None:
    db = thai_root / "เธเนเธญเธกเธนเธฅ" / "p9-rules.sqlite"
    migrator, _profiles_before = _at_0008(db)
    migrator.upgrade("head")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        _add_session(conn, "visit")
        _add_output(conn, "first", "visit", "ok")
        with pytest.raises(sqlite3.IntegrityError):
            _add_output(conn, "second", "visit", "ok")
        _add_output(conn, "older", "visit", "superseded")  # only one may count

        link = (
            "INSERT INTO delivery_tokens (id, session_id, token_hash, created_at, expires_at) "
            "VALUES (?, 'visit', ?, '2026-01-01', '2026-01-08')"
        )
        conn.execute(link, ("a", "hash-a"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(link, ("b", "hash-b"))  # a second live link for the same visit
        conn.execute("UPDATE delivery_tokens SET revoked_at = '2026-01-02' WHERE id = 'a'")
        conn.execute(link, ("b", "hash-b"))  # once the first is revoked, a new one may exist

        # A visit that goes takes its finished photos and its links with it.
        conn.execute("DELETE FROM booth_sessions WHERE id = 'visit'")
        assert conn.execute("SELECT COUNT(*) FROM output_assets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM delivery_tokens").fetchone()[0] == 0


def test_downgrade_ends_delivered_visits_as_completed(thai_root: Path) -> None:
    db = thai_root / "เธเนเธญเธกเธนเธฅ" / "p9-round-trip.sqlite"
    migrator, profiles = _at_0008(db)
    migrator.upgrade("head")
    with sqlite3.connect(db) as conn:
        _add_session(conn, "delivered-visit")
        conn.execute("UPDATE booth_sessions SET state = 'delivered'")
        _add_output(conn, "photo", "delivered-visit", "ok")
        conn.commit()

    migrator.downgrade("0008_test_sessions")
    with sqlite3.connect(db) as conn:
        tables = _tables(conn)
        assert "output_assets" not in tables and "delivery_tokens" not in tables
        state = conn.execute("SELECT state FROM booth_sessions").fetchone()[0]
        assert state == "completed"
        assert _profiles(conn) == profiles
    migrator.upgrade("head")
