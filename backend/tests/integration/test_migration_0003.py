"""Migration 0003 (frames and per-layout frame selection): parity, constraints, up/down."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from photobooth.core.db import Base, create_sqlite_engine
from photobooth.core.migrations import Migrator
from photobooth.modules.event_profiles.repository import EventProfileFrameRow
from photobooth.modules.frames.repository import FrameAssetRow

PHASE5_TABLES = {"frame_assets", "event_profile_frames"}
NOW = "2026-09-18 10:00:00.000000"


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_orm_metadata_matches_migrated_schema(thai_root: Path) -> None:
    db = thai_root / "parity.sqlite"
    Migrator(db).upgrade("head")
    assert FrameAssetRow.__table__ is not None and EventProfileFrameRow.__table__ is not None
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


def _seed_frame(conn: sqlite3.Connection, suffix: str = "1") -> None:
    """Insert a frame, a profile and the profile's frame selection (all values are bound)."""
    conn.execute(
        "INSERT OR IGNORE INTO media_assets VALUES (?,'frame',?,'image/png',600,1800,2048,?,?)",
        (f"a{suffix}", f"assets/frame/aa/a{suffix}.png", suffix * 64, NOW),
    )
    conn.execute(
        "INSERT INTO frame_assets VALUES (?,?,'strip_2x6',1,?,'valid','{}',?,?)",
        (f"f{suffix}", f"a{suffix}", f"Gold{suffix}", NOW, NOW),
    )
    conn.execute(
        "INSERT INTO event_profiles (id,name,name_key,title,subtitle,start_button_text,"
        "logo_asset_id,background_asset_id,background_color,primary_color,secondary_color,"
        "button_color,text_color,countdown_seconds,mirror,inactivity_timeout_s,retake_mode,"
        "delivery_mode,is_active,revision,created_at,updated_at,deleted_at) VALUES "
        "(?,?,?,'ยินดีต้อนรับ','','Start',NULL,NULL,'#000000','#000000','#000000','#000000',"
        "'#FFFFFF',5,1,120,'per_photo','local_link',1,1,?,?,NULL)",
        (f"p{suffix}", f"งานแต่ง{suffix}", f"งานแต่ง{suffix}", NOW, NOW),
    )
    conn.execute("INSERT INTO event_profile_layouts VALUES (?,'strip_2x6',0)", (f"p{suffix}",))
    conn.execute(
        "INSERT INTO event_profile_frames VALUES (?,'strip_2x6',?)", (f"p{suffix}", f"f{suffix}")
    )
    conn.commit()


def test_upgrade_seed_constraints_downgrade_upgrade(thai_root: Path) -> None:
    db = thai_root / "ฐานข้อมูล" / "p5.sqlite"
    migrator = Migrator(db)
    migrator.upgrade("0002_admin_profiles")
    assert not (PHASE5_TABLES & _tables(db))

    migrator.upgrade("0003_frames")
    assert _tables(db) >= PHASE5_TABLES
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        _seed_frame(conn)
        with pytest.raises(sqlite3.IntegrityError):  # a selected frame can not be removed
            conn.execute("DELETE FROM frame_assets WHERE id='f1'")
        with pytest.raises(sqlite3.IntegrityError):  # the frame's file can not be removed
            conn.execute("DELETE FROM media_assets WHERE id='a1'")
        with pytest.raises(sqlite3.IntegrityError):  # one frame per layout per profile
            conn.execute("INSERT INTO event_profile_frames VALUES ('p1','strip_2x6','f1')")
        with pytest.raises(sqlite3.IntegrityError):  # frame names are unique per layout
            conn.execute(
                "INSERT INTO frame_assets VALUES (?,?,'strip_2x6',1,?,'valid','{}',?,?)",
                ("fx", "a1", "Gold1", NOW, NOW),
            )
        # Deleting the profile releases its selection (cascade).
        conn.execute("DELETE FROM event_profiles WHERE id='p1'")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM event_profile_frames").fetchone()[0] == 0

    migrator.downgrade("0002_admin_profiles")
    assert not (PHASE5_TABLES & _tables(db))
    assert {"event_profiles", "media_assets"} <= _tables(db)
    assert migrator.current_revision() == "0002_admin_profiles"

    migrator.upgrade("head")
    assert _tables(db) >= PHASE5_TABLES
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        _seed_frame(conn, suffix="2")  # the tables are usable again after the round trip
