"""Migration 0002 (admin users, media assets, Event Profiles): schema parity and data round trip."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from photobooth.core.db import Base, create_sqlite_engine
from photobooth.core.migrations import Migrator
from photobooth.modules.assets.repository import MediaAssetRow
from photobooth.modules.auth.repository import AdminUserRow
from photobooth.modules.event_profiles.repository import EventProfileLayoutRow, EventProfileRow

PHASE3_TABLES = {"admin_users", "media_assets", "event_profiles", "event_profile_layouts"}
ORM_TABLES = (AdminUserRow, MediaAssetRow, EventProfileRow, EventProfileLayoutRow)


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _indexes(db: Path, table: str) -> dict[str, str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,)
        ).fetchall()
    return {name: sql or "" for name, sql in rows}


def test_orm_metadata_matches_migrated_schema(thai_root: Path) -> None:
    db = thai_root / "parity.sqlite"
    Migrator(db).upgrade("head")
    assert all(row.__table__ is not None for row in ORM_TABLES)
    engine = create_sqlite_engine(db)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn, opts={"compare_type": True, "compare_server_default": False}
            )
            diff = [
                d
                for d in compare_metadata(context, Base.metadata)
                if not (isinstance(d, tuple) and d[0] == "remove_table" and d[1].name == "app_meta")
            ]
    finally:
        engine.dispose()
    assert diff == []
    indexes = _indexes(db, "event_profiles")
    assert "WHERE is_active = 1" in indexes["uq_event_profiles_single_active"]
    assert "WHERE deleted_at IS NULL" in indexes["uq_event_profiles_live_name"]


def _seed(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        now = "2026-09-17 10:00:00.000000"
        conn.execute(
            "INSERT INTO admin_users VALUES ('u1','admin','$argon2id$x',?,?,NULL)", (now, now)
        )
        conn.execute(
            "INSERT INTO media_assets VALUES ('a1','logo','assets/logo/aa/aa.png','image/png',"
            "10,10,100,?,?)",
            ("a" * 64, now),
        )
        conn.execute(
            "INSERT INTO event_profiles (id,name,name_key,title,subtitle,start_button_text,"
            "logo_asset_id,background_asset_id,background_color,primary_color,secondary_color,"
            "button_color,text_color,countdown_seconds,mirror,inactivity_timeout_s,retake_mode,"
            "delivery_mode,is_active,revision,created_at,updated_at,deleted_at) VALUES "
            "('p1','งานแต่ง','งานแต่ง','ยินดีต้อนรับ','','Start','a1',NULL,'#000000','#000000',"
            "'#000000','#000000','#FFFFFF',5,1,120,'per_photo','local_link',1,1,?,?,NULL)",
            (now, now),
        )
        conn.execute("INSERT INTO event_profile_layouts VALUES ('p1','strip_2x6',0)")
        conn.commit()


def test_upgrade_seed_downgrade_upgrade(thai_root: Path) -> None:
    db = thai_root / "ฐานข้อมูล" / "p3.sqlite"
    migrator = Migrator(db)
    migrator.upgrade("0001_baseline")
    assert not (PHASE3_TABLES & _tables(db))
    migrator.upgrade("0002_admin_profiles")
    assert _tables(db) >= PHASE3_TABLES
    _seed(db)

    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):  # asset in use can not be removed
            conn.execute("DELETE FROM media_assets WHERE id='a1'")
        with pytest.raises(sqlite3.IntegrityError):  # countdown fixed
            conn.execute("UPDATE event_profiles SET countdown_seconds=3 WHERE id='p1'")
        with pytest.raises(sqlite3.IntegrityError):  # deleted profile can not stay active
            conn.execute("UPDATE event_profiles SET deleted_at='2026-09-17' WHERE id='p1'")

    migrator.downgrade("0001_baseline")
    assert not (PHASE3_TABLES & _tables(db))
    assert "app_meta" in _tables(db)
    assert migrator.current_revision() == "0001_baseline"

    migrator.upgrade("0002_admin_profiles")
    assert _tables(db) >= PHASE3_TABLES
    _seed(db)  # clean tables again after the round trip
    migrator.upgrade("head")  # later revisions carry the seeded rows forward
    assert migrator.current_revision() == migrator.head_revision()
