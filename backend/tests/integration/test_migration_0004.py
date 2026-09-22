"""Migration 0004: built-in frames, complete themes, safe default frames for existing profiles."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from photobooth.core.db import create_sqlite_engine
from photobooth.core.migrations import Migrator
from photobooth.modules.event_profiles.repository import SqlEventProfileRepository
from photobooth.modules.frames.builtin import FAMILIES, LAYOUTS, builtin_frame_id
from photobooth.modules.themes.domain import TOKEN_KEYS, contrast_problems, is_dark

NOW = "2026-09-18 10:00:00.000000"
LEGACY = ("background_color", "primary_color", "secondary_color", "button_color", "text_color")
KEPT = (
    "name, title, subtitle, start_button_text, logo_asset_id, background_asset_id, "
    "countdown_seconds, mirror, inactivity_timeout_s, retake_mode, delivery_mode, is_active, "
    "revision, created_at, updated_at, deleted_at"
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _profile(
    conn: sqlite3.Connection,
    pid: str,
    colours: tuple[str, str, str, str, str],
    layouts: tuple[str, ...],
    *,
    deleted: bool = False,
    active: bool = False,
) -> None:
    conn.execute(
        "INSERT INTO event_profiles (id,name,name_key,title,subtitle,start_button_text,"
        "logo_asset_id,background_asset_id,background_color,primary_color,secondary_color,"
        "button_color,text_color,countdown_seconds,mirror,inactivity_timeout_s,retake_mode,"
        "delivery_mode,is_active,revision,created_at,updated_at,deleted_at) VALUES "
        "(?,?,?,'ยินดีต้อนรับ','ถ่ายรูปกัน','เริ่ม',NULL,NULL,?,?,?,?,?,5,0,300,'all','local_link',"
        "?,7,?,?,?)",
        (
            pid,
            f"งาน {pid}",
            f"งาน {pid}",
            *colours,
            int(active),
            NOW,
            NOW,
            NOW if deleted else None,
        ),
    )
    for index, key in enumerate(layouts):
        conn.execute("INSERT INTO event_profile_layouts VALUES (?,?,?)", (pid, key, index))


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO media_assets VALUES ('a1','frame','assets/frame/aa/a1.png','image/png',"
        "600,1800,2048,?,?)",
        ("1" * 64, NOW),
    )
    # An uploaded frame that happens to use a built-in name.
    conn.execute(
        "INSERT INTO frame_assets VALUES ('f1','a1','strip_2x6',1,'Midnight','valid','{}',?,?)",
        (NOW, NOW),
    )
    _profile(conn, "p1", ("#101418", "#2F6FD6", "#FFB020", "#2F6FD6", "#F4F6F8"),
             ("strip_2x6", "print_4x6"), active=True)  # fmt: skip
    conn.execute("INSERT INTO event_profile_frames VALUES ('p1','strip_2x6','f1')")
    _profile(conn, "p2", ("#FFFFFF", "#BE185D", "#9F1239", "#BE185D", "#111111"),
             ("print_3x4",), deleted=True)  # fmt: skip
    _profile(conn, "p3", ("#777777", "#787878", "#767676", "#777777", "#797979"),
             ("strip_2x6", "print_3x4", "print_4x6"))  # fmt: skip
    conn.commit()


def _kept(conn: sqlite3.Connection) -> list[tuple[object, ...]]:
    return conn.execute(f"SELECT {KEPT} FROM event_profiles ORDER BY id").fetchall()  # noqa: S608


def _selections(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    return set(conn.execute("SELECT profile_id, template_key, frame_id FROM event_profile_frames"))


def test_upgrade_converts_colours_adds_builtins_and_defaults_without_losing_data(
    thai_root: Path,
) -> None:
    db = thai_root / "ฐานข้อมูล" / "p5b.sqlite"
    migrator = Migrator(db)
    migrator.upgrade("0003_frames")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        _seed(conn)
        before = _kept(conn)

    migrator.upgrade("0004_builtin_frames_themes")
    with sqlite3.connect(db) as conn:
        assert _kept(conn) == before  # every other setting, flag and revision unchanged
        columns = _columns(conn, "event_profiles")
        assert "theme" in columns and not (set(LEGACY) & columns)
        themes = dict(conn.execute("SELECT id, theme FROM event_profiles"))
        for raw in themes.values():
            theme = json.loads(raw)
            assert set(theme["tokens"]) == set(TOKEN_KEYS)
            assert contrast_problems(theme["tokens"]) == []  # even p3's grey-on-grey
            assert theme["source"] == "custom"
        assert is_dark(json.loads(themes["p1"])["tokens"])
        assert not is_dark(json.loads(themes["p2"])["tokens"])

        builtins = conn.execute(
            "SELECT id, family, template_key, name FROM frame_assets WHERE builtin = 1"
        ).fetchall()
        assert len(builtins) == len(FAMILIES) * len(LAYOUTS)
        assert conn.execute("SELECT name FROM frame_assets WHERE id = 'f1'").fetchone()[0] == (
            "Midnight (uploaded)"
        )
        p3_family = "midnight" if is_dark(json.loads(themes["p3"])["tokens"]) else "minimal_light"
        assert _selections(conn) == {
            ("p1", "strip_2x6", "f1"),  # an existing choice is never replaced
            ("p1", "print_4x6", builtin_frame_id("midnight", "print_4x6")),  # dark theme
            ("p2", "print_3x4", builtin_frame_id("minimal_light", "print_3x4")),  # light theme
            *(("p3", key, builtin_frame_id(p3_family, key)) for key in LAYOUTS),
        }
        assert {row[1] for row in builtins} == {f.id for f in FAMILIES}

    # The application (at head) reads every migrated profile.
    migrator.upgrade("head")
    engine = create_sqlite_engine(db)
    try:
        repository = SqlEventProfileRepository(engine)
        profiles = {p.id: p for p in repository.list_profiles(include_deleted=True)}
        assert set(profiles) == {"p1", "p2", "p3"}
        assert profiles["p1"].is_active and profiles["p2"].deleted
        assert profiles["p1"].settings.title == "ยินดีต้อนรับ"
        assert profiles["p1"].settings.theme.problems() == []
    finally:
        engine.dispose()


def test_uploads_with_builtin_names_get_the_first_free_name(thai_root: Path) -> None:
    """P5R-001: 'Midnight' and 'Midnight (uploaded)' may both exist before the upgrade."""
    db = thai_root / "clash.sqlite"
    migrator = Migrator(db)
    migrator.upgrade("0003_frames")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        _seed(conn)  # f1 'Midnight' (strip, selected by p1)
        for suffix, name in (("2", "Midnight (uploaded)"), ("3", "Midnight (uploaded 2)")):
            conn.execute(
                "INSERT INTO media_assets VALUES (?,'frame',?,'image/png',600,1800,2048,?,?)",
                (f"a{suffix}", f"assets/frame/aa/a{suffix}.png", suffix * 64, NOW),
            )
            conn.execute(
                "INSERT INTO frame_assets VALUES (?,?,'strip_2x6',1,?,'valid','{}',?,?)",
                (f"f{suffix}", f"a{suffix}", name, NOW, NOW),
            )
        conn.commit()
    migrator.upgrade("0004_builtin_frames_themes")
    with sqlite3.connect(db) as conn:
        names = dict(conn.execute("SELECT id, name FROM frame_assets WHERE builtin = 0"))
        assert names == {
            "f1": "Midnight (uploaded 3)",
            "f2": "Midnight (uploaded)",
            "f3": "Midnight (uploaded 2)",
        }
        assert ("p1", "strip_2x6", "f1") in _selections(conn)  # the selection is kept
        builtin = conn.execute(
            "SELECT COUNT(*) FROM frame_assets WHERE builtin = 1 AND name = 'Midnight'"
        ).fetchone()[0]
        assert builtin == len(LAYOUTS)


def test_downgrade_restores_the_old_columns_and_upgrade_again_works(thai_root: Path) -> None:
    db = thai_root / "round-trip.sqlite"
    migrator = Migrator(db)
    migrator.upgrade("0003_frames")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        _seed(conn)
        before = _kept(conn)
    migrator.upgrade("0004_builtin_frames_themes")
    migrator.downgrade("0003_frames")
    with sqlite3.connect(db) as conn:
        assert _kept(conn) == before
        columns = _columns(conn, "event_profiles")
        assert set(LEGACY) <= columns and "theme" not in columns
        assert not ({"builtin", "family"} & _columns(conn, "frame_assets"))
        assert conn.execute("SELECT COUNT(*) FROM frame_assets").fetchone()[0] == 1  # only f1
        assert _selections(conn) == {("p1", "strip_2x6", "f1")}
        colours = conn.execute(
            "SELECT background_color, primary_color, secondary_color, button_color, text_color "
            "FROM event_profiles WHERE id='p1'"
        ).fetchone()
        assert all(c.startswith("#") and len(c) == 7 for c in colours)
    migrator.upgrade("0004_builtin_frames_themes")
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM frame_assets WHERE builtin = 1").fetchone()[0] == 9
        )
