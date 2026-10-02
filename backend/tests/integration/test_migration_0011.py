"""Migration 0011: the retention policy (seeded with the provisional defaults) and its runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.integration.test_migration_0005 import _prepare, _tables
from tests.integration.test_migration_0006 import _profiles
from tests.integration.test_migration_0008 import _add_session


def test_the_policy_arrives_with_its_defaults_and_nothing_else_changes(thai_root: Path) -> None:
    db = thai_root / "เก็บรักษา" / "p11.sqlite"
    migrator, _before = _prepare(db)
    migrator.upgrade("0010_activity_log")
    with sqlite3.connect(db) as conn:
        _add_session(conn, "earlier-visit")
        conn.commit()
        profiles = _profiles(conn)
        before = conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall()

    migrator.upgrade("0011_retention")
    with sqlite3.connect(db) as conn:
        assert {"retention_policy", "retention_runs"} <= _tables(conn)
        row = conn.execute(
            "SELECT originals_days, outputs_days, link_days, temp_hours, metadata_mode, "
            "metadata_days, activity_log_days, backup_days, app_log_days, revision "
            "FROM retention_policy"
        ).fetchall()
        assert row == [(7, 30, 7, 24, "keep", 90, 90, 7, 14, 1)]
        assert _profiles(conn) == profiles
        assert conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall() == before
        try:
            conn.execute("UPDATE retention_policy SET metadata_mode = 'forever'")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("an unknown metadata mode was accepted")

    migrator.downgrade("0010_activity_log")
    with sqlite3.connect(db) as conn:
        assert not {"retention_policy", "retention_runs"} & _tables(conn)
        assert conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall() == before
