"""Migration 0012: retention policies per Event Profile, frozen in each visit (P11-9).

Every existing profile, deleted ones included, selects "Standard", which carries the values the
booth's single 0011 policy had (an organizer's own changes included). Every existing visit
freezes those values, so no deadline moves with the upgrade. The booth-wide settings move to the
housekeeping row. Nothing else changes, and the downgrade gives the 0011 policy back.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests.integration.test_migration_0005 import _prepare, _tables
from tests.integration.test_migration_0006 import _profiles
from tests.integration.test_migration_0008 import _add_session

STANDARD = "00000000-0000-4000-8000-000000000001"


def test_existing_profiles_and_visits_keep_the_policy_they_had(thai_root: Path) -> None:
    db = thai_root / "เก็บรักษา" / "p12.sqlite"
    migrator, _before = _prepare(db)
    migrator.upgrade("0011_retention")
    with sqlite3.connect(db) as conn:
        _add_session(conn, "earlier-visit")
        # The organizer had changed the booth's policy under 0011.
        conn.execute(
            "UPDATE retention_policy SET originals_days = 3, outputs_days = 20, link_days = 5, "
            "metadata_mode = 'anonymize', metadata_days = 60, backup_days = 9, revision = 4"
        )
        conn.commit()
        profiles = _profiles(conn)
        sessions_before = conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall()
        assert profiles, "the seeded database has profiles"

    migrator.upgrade("0012_policy_per_event")
    with sqlite3.connect(db) as conn:
        tables = _tables(conn)
        assert {"retention_policies", "retention_housekeeping"} <= tables
        assert "retention_policy" not in tables
        policies = conn.execute(
            "SELECT id, name, originals_days, outputs_days, link_days, metadata_mode, "
            "metadata_days, is_default FROM retention_policies"
        ).fetchall()
        assert policies == [(STANDARD, "Standard", 3, 20, 5, "anonymize", 60, 1)]
        house = conn.execute(
            "SELECT temp_hours, activity_log_days, backup_days, app_log_days, revision "
            "FROM retention_housekeeping"
        ).fetchall()
        assert house == [(24, 90, 9, 14, 5)]  # a check made before can not confirm after
        chosen = conn.execute("SELECT DISTINCT retention_policy_id FROM event_profiles").fetchall()
        assert chosen == [(STANDARD,)]
        frozen = [
            json.loads(raw) for (raw,) in conn.execute("SELECT retention FROM booth_sessions")
        ]
        assert frozen == [
            {
                "policy_id": STANDARD,
                "policy_name": "Standard",
                "originals_days": 3,
                "outputs_days": 20,
                "link_days": 5,
                "records_mode": "anonymize",
                "records_days": 60,
            }
        ]
        # Everything else about profiles and visits is as it was.
        kept = [
            {k: v for k, v in profile.items() if k != "retention_policy_id"}
            for profile in _profiles(conn)
        ]
        assert kept == profiles
        after = conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall()
        assert [row[:-1] for row in after] == sessions_before
        try:
            conn.execute("UPDATE retention_policies SET metadata_mode = 'forever'")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("an unknown metadata mode was accepted")
        try:
            conn.execute(
                "INSERT INTO retention_policies VALUES ('x', 'Other', 'other', 1, 1, 1, 'keep', 1, "
                "1, 1, '2026-10-03 00:00:00', NULL)"
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("a second default policy was accepted")

    migrator.downgrade("0011_retention")
    with sqlite3.connect(db) as conn:
        tables = _tables(conn)
        assert "retention_policy" in tables
        assert not {"retention_policies", "retention_housekeeping"} & tables
        single = conn.execute(
            "SELECT originals_days, outputs_days, link_days, temp_hours, metadata_mode, "
            "metadata_days, activity_log_days, backup_days, app_log_days FROM retention_policy"
        ).fetchall()
        assert single == [(3, 20, 5, 24, "anonymize", 60, 90, 9, 14)]
        assert _profiles(conn) == profiles
        assert (
            conn.execute("SELECT * FROM booth_sessions ORDER BY id").fetchall() == sessions_before
        )
