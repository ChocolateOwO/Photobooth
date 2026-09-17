"""Concurrent backup processes must all be published and all recorded in the ledger."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

from photobooth.core.migrations import Migrator

_BACKUP = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from photobooth.core.sqlite_backup import SqliteBackupService
    SqliteBackupService(Path(sys.argv[2])).create_backup(Path(sys.argv[1]), "dummy")
    """
)


def test_parallel_backups_keep_every_ledger_entry(thai_root: Path) -> None:
    db = thai_root / "db" / "photobooth.sqlite"
    Migrator(db).upgrade("head")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO app_meta (key, value) VALUES ('instance', 'dummy')")
    backups = thai_root / "backups"

    workers = 6
    processes = [
        subprocess.Popen([sys.executable, "-c", _BACKUP, str(db), str(backups)])
        for _ in range(workers)
    ]
    assert [p.wait(timeout=120) for p in processes] == [0] * workers

    ledger = json.loads((backups / "BACKUPS.json").read_text(encoding="utf-8"))
    files = sorted(backups.glob("dummy-*.sqlite"))
    assert len(files) == workers
    assert len(ledger) == workers
    assert {entry["path"] for entry in ledger} == {str(f) for f in files}
    assert not list(backups.glob("*.tmp"))
    assert not list(backups.glob("*.partial"))
