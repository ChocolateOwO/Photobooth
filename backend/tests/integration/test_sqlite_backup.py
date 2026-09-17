"""Backups use the online API and include committed rows still living in the WAL."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from photobooth.core.errors import BackupError
from photobooth.core.migrations import Migrator
from photobooth.core.sqlite_backup import SqliteBackupService


def _prepare(db: Path, instance: str = "dummy") -> None:
    Migrator(db).upgrade("head")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO app_meta (key, value) VALUES ('instance', ?)", (instance,))


def test_backup_contains_uncheckpointed_wal_rows(thai_root: Path) -> None:
    db = thai_root / "db" / "photobooth.sqlite"
    _prepare(db)

    writer = sqlite3.connect(db)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.executemany(
            "INSERT INTO app_meta (key, value) VALUES (?, ?)",
            [(f"row-{i}", "ค่า") for i in range(50)],
        )
        writer.commit()
        wal = db.with_name(db.name + "-wal")
        assert wal.exists() and wal.stat().st_size > 0

        # A naive raw copy of the main file misses the committed rows still in the WAL.
        naive = thai_root / "naive-copy.sqlite"
        shutil.copyfile(db, naive)
        with sqlite3.connect(naive) as conn:
            naive_rows = conn.execute(
                "SELECT COUNT(*) FROM app_meta WHERE key LIKE 'row-%'"
            ).fetchone()[0]
        assert naive_rows < 50

        service = SqliteBackupService(thai_root / "backups")
        record = service.create_backup(db, "dummy")
    finally:
        writer.close()

    backup = Path(record.path)
    assert backup.is_file()
    assert "ทดสอบ" in record.path
    assert record.integrity == "ok"
    assert record.alembic_revision == "0003_frames"
    assert record.instance == "dummy"
    assert backup.name.startswith("dummy-") and backup.name.endswith("-0003_frames.sqlite")
    assert not backup.with_name(backup.name + "-wal").exists()
    with sqlite3.connect(backup) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM app_meta WHERE key LIKE 'row-%'").fetchone()[0]
    assert rows == 50

    ledger = json.loads(service.ledger_path.read_text(encoding="utf-8"))
    assert ledger[-1]["sha256"] == record.sha256
    assert service.read_ledger()[-1] == record


def test_backup_refuses_other_instance(thai_root: Path) -> None:
    db = thai_root / "main.sqlite"
    _prepare(db, instance="main")
    service = SqliteBackupService(thai_root / "backups")
    with pytest.raises(BackupError, match="instance mismatch"):
        service.create_backup(db, "dummy")
    assert not list((thai_root / "backups").glob("*.sqlite*"))


def test_verify_rejects_corrupt_backup(thai_root: Path) -> None:
    db = thai_root / "x.sqlite"
    _prepare(db)
    service = SqliteBackupService(thai_root / "backups")
    record = service.create_backup(db, "dummy")
    path = Path(record.path)
    data = bytearray(path.read_bytes())
    for i in range(1024, min(len(data), 4096)):
        data[i] = 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises((BackupError, sqlite3.DatabaseError)):
        service.verify(path, "dummy")


def test_backup_of_missing_database_fails(thai_root: Path) -> None:
    with pytest.raises(BackupError, match="not found"):
        SqliteBackupService(thai_root / "b").create_backup(thai_root / "nope.sqlite", "dummy")
