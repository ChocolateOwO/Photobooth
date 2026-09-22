"""Migration 0005: per-layout selections become an ordered list of available frames."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from photobooth.core.db import create_sqlite_engine
from photobooth.core.migrations import Migrator
from photobooth.modules.event_profiles.repository import SqlEventProfileRepository
from photobooth.modules.frames.builtin import LAYOUTS, builtin_frame_id
from photobooth.modules.themes.domain import PRESETS

NOW = "2026-09-21 10:00:00.000000"
DARK = json.dumps({"tokens": PRESETS["midnight_blue"].tokens, "source": "preset",
                   "preset": "midnight_blue", "palette": []})  # fmt: skip
LIGHT = json.dumps({"tokens": PRESETS["minimal_light"].tokens, "source": "custom",
                    "preset": None, "palette": ["#FFFFFF"]})  # fmt: skip
KEPT = (
    "id, name, title, subtitle, start_button_text, logo_asset_id, background_asset_id, theme, "
    "countdown_seconds, mirror, inactivity_timeout_s, retake_mode, delivery_mode, is_active, "
    "revision, created_at, updated_at, deleted_at"
)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _profile(
    conn: sqlite3.Connection, pid: str, theme: str, layouts: tuple[str, ...], **flags: bool
) -> None:
    conn.execute(
        "INSERT INTO event_profiles (id,name,name_key,title,subtitle,start_button_text,"
        "logo_asset_id,background_asset_id,theme,countdown_seconds,mirror,inactivity_timeout_s,"
        "retake_mode,delivery_mode,is_active,revision,created_at,updated_at,deleted_at) VALUES "
        "(?,?,?,'งานเลี้ยง','ยิ้ม','เริ่ม',?,?,?,5,0,300,'all','local_link',?,4,?,?,?)",
        (
            pid,
            f"งาน {pid}",
            f"งาน {pid}",
            "logo1" if pid == "p1" else None,
            "bg1" if pid == "p1" else None,
            theme,
            int(flags.get("active", False)),
            NOW,
            NOW,
            NOW if flags.get("deleted", False) else None,
        ),
    )
    for index, key in enumerate(layouts):
        conn.execute("INSERT INTO event_profile_layouts VALUES (?,?,?)", (pid, key, index))


def _seed(conn: sqlite3.Connection) -> None:
    for asset, kind in (("logo1", "logo"), ("bg1", "background"), ("a1", "frame"), ("a2", "frame")):
        conn.execute(
            "INSERT INTO media_assets VALUES (?,?,?,'image/png',600,1800,2048,?,?)",
            (asset, kind, f"assets/{kind}/aa/{asset}.png", asset[-1] * 64, NOW),
        )
    for fid, asset, name in (("f1", "a1", "Our strip"), ("f2", "a2", "Unused upload")):
        conn.execute(
            "INSERT INTO frame_assets VALUES (?,?,'strip_2x6',1,?,'valid','{}',?,?,0,NULL)",
            (fid, asset, name, NOW, NOW),
        )
    # p1: active, dark; its strip uses an upload, its 4x6 a built-in frame.
    _profile(conn, "p1", DARK, ("print_4x6", "strip_2x6"), active=True)
    conn.execute("INSERT INTO event_profile_frames VALUES ('p1','strip_2x6','f1')")
    conn.execute(
        "INSERT INTO event_profile_frames VALUES ('p1','print_4x6',?)",
        (builtin_frame_id("celebration_gold", "print_4x6"),),
    )
    # p2: deleted, light, a layout left without a frame ("No frame selected").
    _profile(conn, "p2", LIGHT, ("print_3x4",), deleted=True)
    # p3: two layouts, one chosen and one left empty.
    _profile(conn, "p3", DARK, ("strip_2x6", "print_3x4"))
    conn.execute(
        "INSERT INTO event_profile_frames VALUES ('p3','strip_2x6',?)",
        (builtin_frame_id("minimal_light", "strip_2x6"),),
    )
    conn.commit()


def _available(conn: sqlite3.Connection) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for pid, fid in conn.execute(
        "SELECT profile_id, frame_id FROM event_profile_available_frames "
        "ORDER BY profile_id, position"
    ):
        result.setdefault(pid, []).append(fid)
    return result


def _prepare(db: Path) -> tuple[Migrator, list[tuple[object, ...]]]:
    migrator = Migrator(db)
    migrator.upgrade("0004_builtin_frames_themes")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        _seed(conn)
        before = conn.execute(f"SELECT {KEPT} FROM event_profiles ORDER BY id").fetchall()  # noqa: S608
    return migrator, before


def test_selections_become_ordered_available_frames_and_nothing_else_changes(
    thai_root: Path,
) -> None:
    db = thai_root / "ฐานข้อมูล" / "p5c.sqlite"
    migrator, before = _prepare(db)
    migrator.upgrade("0005_available_frames")
    with sqlite3.connect(db) as conn:
        after = conn.execute(f"SELECT {KEPT} FROM event_profiles ORDER BY id").fetchall()  # noqa: S608
        assert after == before  # theme, logo, background, texts, flags, revision: unchanged
        assert not ({"event_profile_frames", "event_profile_layouts"} & _tables(conn))
        assert conn.execute("SELECT DISTINCT allow_surprise_me FROM event_profiles").fetchall() == [
            (0,)
        ]
        assert _available(conn) == {
            # In the old layout order; the uploaded frame kept, nothing else added.
            "p1": [builtin_frame_id("celebration_gold", "print_4x6"), "f1"],
            # A layout without a frame keeps being offered through its built-in default.
            "p2": [builtin_frame_id("minimal_light", "print_3x4")],
            "p3": [
                builtin_frame_id("minimal_light", "strip_2x6"),
                builtin_frame_id("midnight", "print_3x4"),
            ],
        }
        # The unused upload is never switched on by the migration, and no file is lost.
        assert all("f2" not in frames for frames in _available(conn).values())
        assert (
            conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 4 + len(LAYOUTS) * 3
        )

    migrator.upgrade("head")  # the app reads the latest schema (sizes, see 0006)
    engine = create_sqlite_engine(db)
    try:
        profiles = {p.id: p for p in SqlEventProfileRepository(engine).list_profiles(True)}
        assert profiles["p1"].is_active
        assert profiles["p1"].settings.enabled_layouts == ("print_4x6", "strip_2x6")
        assert profiles["p1"].settings.logo_asset_id == "logo1"
        assert profiles["p1"].settings.theme.preset == "midnight_blue"
        assert profiles["p2"].deleted and profiles["p2"].settings.theme.palette == ("#FFFFFF",)
    finally:
        engine.dispose()


def test_downgrade_restores_layouts_and_one_frame_each_then_upgrade_again(thai_root: Path) -> None:
    db = thai_root / "round-trip-0005.sqlite"
    migrator, before = _prepare(db)
    migrator.upgrade("0005_available_frames")  # 0006 keeps sizes, not single frames
    migrator.downgrade("0004_builtin_frames_themes")
    with sqlite3.connect(db) as conn:
        assert conn.execute(f"SELECT {KEPT} FROM event_profiles ORDER BY id").fetchall() == before  # noqa: S608
        layouts = conn.execute(
            "SELECT profile_id, template_key FROM event_profile_layouts "
            "ORDER BY profile_id, sort_order"
        ).fetchall()
        assert layouts == [
            ("p1", "print_4x6"),
            ("p1", "strip_2x6"),
            ("p2", "print_3x4"),
            ("p3", "strip_2x6"),
            ("p3", "print_3x4"),
        ]
        frames = set(
            conn.execute("SELECT profile_id, template_key, frame_id FROM event_profile_frames")
        )
        assert ("p1", "strip_2x6", "f1") in frames
        assert "allow_surprise_me" not in {
            r[1] for r in conn.execute("PRAGMA table_info(event_profiles)")
        }
    migrator.upgrade("0005_available_frames")
    with sqlite3.connect(db) as conn:
        assert _available(conn)["p1"] == [builtin_frame_id("celebration_gold", "print_4x6"), "f1"]
