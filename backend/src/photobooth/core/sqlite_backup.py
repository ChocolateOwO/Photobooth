"""WAL-safe SQLite backups via the online backup API, with verification and a ledger."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from photobooth.core.errors import BackupError
from photobooth.core.file_lock import ExclusiveFileLock

LEDGER_FILENAME = "BACKUPS.json"
LEDGER_LOCK_FILENAME = ".BACKUPS.lock"


@dataclass(frozen=True)
class BackupRecord:
    path: str
    instance: str
    alembic_revision: str | None
    sha256: str
    size_bytes: int
    integrity: str
    created_at: str


@contextmanager
def _connect_readonly(path: Path) -> Iterator[sqlite3.Connection]:
    # as_uri() percent-encodes non-ASCII (Thai) path segments correctly for SQLite URIs.
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        yield conn
    finally:
        conn.close()


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[str, ...] = ()) -> str | None:
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else str(row[0])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SqliteBackupService:
    """Creates and verifies database backups. Never copies the raw `.sqlite` file."""

    def __init__(self, backups_dir: Path) -> None:
        self._dir = backups_dir

    @property
    def ledger_path(self) -> Path:
        return self._dir / LEDGER_FILENAME

    def create_backup(self, db_path: Path, expected_instance: str) -> BackupRecord:
        if not db_path.is_file():
            raise BackupError(f"database not found: {db_path}")
        self._dir.mkdir(parents=True, exist_ok=True)
        with _connect_readonly(db_path) as probe:
            revision = _scalar(probe, "SELECT version_num FROM alembic_version")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        unique = secrets.token_hex(3)  # concurrent backups never share a partial or final name
        final = self._dir / f"{expected_instance}-{stamp}-{unique}-{revision or 'norev'}.sqlite"
        partial = final.with_suffix(".sqlite.partial")

        with closing(sqlite3.connect(db_path)) as source, closing(sqlite3.connect(partial)) as dest:
            source.backup(dest)  # online backup API: includes committed pages still in the WAL
            dest.execute("PRAGMA journal_mode=DELETE")
            dest.commit()

        try:
            record = self.verify(partial, expected_instance)
        except BackupError:
            partial.unlink(missing_ok=True)
            raise
        os.replace(partial, final)
        record = BackupRecord(**{**asdict(record), "path": str(final)})
        self._append_ledger(record)
        return record

    def verify(self, backup_path: Path, expected_instance: str) -> BackupRecord:
        if not backup_path.is_file():
            raise BackupError(f"backup not found: {backup_path}")
        with _connect_readonly(backup_path) as conn:
            integrity = _scalar(conn, "PRAGMA integrity_check")
            revision = _scalar(conn, "SELECT version_num FROM alembic_version")
            instance = _scalar(conn, "SELECT value FROM app_meta WHERE key = ?", ("instance",))
        if integrity != "ok":
            raise BackupError(f"integrity_check failed for {backup_path}: {integrity}")
        if instance != expected_instance:
            raise BackupError(
                f"backup instance mismatch: expected '{expected_instance}', found '{instance}'"
            )
        return BackupRecord(
            path=str(backup_path),
            instance=instance,
            alembic_revision=revision,
            sha256=_sha256(backup_path),
            size_bytes=backup_path.stat().st_size,
            integrity=integrity,
            created_at=datetime.now(UTC).isoformat(),
        )

    def read_ledger(self) -> list[BackupRecord]:
        if not self.ledger_path.is_file():
            return []
        raw = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        return [BackupRecord(**item) for item in raw]

    def _append_ledger(self, record: BackupRecord) -> None:
        """Serialized read-modify-write across processes; unique temp file per writer."""
        try:
            with ExclusiveFileLock(self._dir / LEDGER_LOCK_FILENAME):
                entries = [asdict(r) for r in self.read_ledger()]
                entries.append(asdict(record))
                tmp = self._dir / f".{LEDGER_FILENAME}.{secrets.token_hex(6)}.tmp"
                tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, self.ledger_path)
        except (OSError, ValueError) as exc:
            raise BackupError(
                f"backup {record.path} is published and verified, but the ledger update failed "
                f"({exc}); re-run the ledger update before relying on {LEDGER_FILENAME}"
            ) from exc

    def reconcile(self) -> None:
        """Drop ledger entries whose backup file is gone (deleted by retention, or by hand),
        under the same lock as writers. Safe to repeat."""
        if not self.ledger_path.is_file():
            return
        with ExclusiveFileLock(self._dir / LEDGER_LOCK_FILENAME):
            records = self.read_ledger()
            kept = [asdict(r) for r in records if (self._dir / Path(r.path).name).is_file()]
            if len(kept) == len(records):
                return
            tmp = self._dir / f".{LEDGER_FILENAME}.{secrets.token_hex(6)}.tmp"
            tmp.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.ledger_path)
