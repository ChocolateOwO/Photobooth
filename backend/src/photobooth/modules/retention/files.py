"""This instance's own files that retention may delete: temporary files, backups, rotated logs.

Every folder must lie inside the instance root, and a file is a candidate only when it is a
regular file (not a link or junction) whose real path is still inside its folder, so a cleanup
can never reach Main, another instance or anything else on the machine. The same checked list is
used both to pick the backup that must be kept and to delete, so nothing outside can ever take
the newest backup's place (P11-004). One file that will not go (open elsewhere, locked by
antivirus) is counted as failed and the rest go on (P11-010).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from photobooth.modules.retention.domain import RetentionError

# A temporary file the storage writes before it moves a photo into place (left by a crash).
_STORAGE_TEMP = re.compile(r"^\..+\.[0-9a-f]{12}\.tmp$")
# A backup copy the backup command never finished (left by a crash) and the ledger's own
# temporary file. Their age (temp_hours) is far beyond any backup still being written (P11-005).
_BACKUP_TEMP = re.compile(r"^(?:[a-z]+-.+\.sqlite\.partial|\.BACKUPS\.json\.[0-9a-f]{12}\.tmp)$")
# Backups made by the backup command: <instance>-<stamp>-<id>-<revision>.sqlite
_BACKUP = re.compile(r"^[a-z]+-.+\.sqlite$")
# Only the application log's own rotated generations: never the log being written, never a
# launcher's console log (held open by the running launcher) (P11-006).
_ROTATED = re.compile(r"^photobooth\.log\.\d+$")

Counted = tuple[int, int, int]


def _real(path: Path) -> Path:
    return Path(os.path.realpath(path))


class InstanceFolders:
    """Implements the retention InstanceFiles port on the local file system."""

    def __init__(
        self,
        instance_root: Path,
        storage: Path,
        backups: Path,
        logs: Path,
        reconcile_backups: Callable[[], None],
    ) -> None:
        self._reconcile_backups = reconcile_backups
        root = _real(instance_root)
        self._folders: dict[str, Path] = {}
        for name, folder in (("storage", storage), ("backups", backups), ("logs", logs)):
            real = _real(folder)
            if real == root or root not in real.parents:
                raise RetentionError(f"the {name} folder is not inside this instance")
            self._folders[name] = real

    # ---- the port --------------------------------------------------------------------------

    def temp(self, before: datetime, dry_run: bool) -> Counted:
        storage = self._folders["storage"]
        found = [
            *self._checked("storage", storage.rglob("*.tmp") if storage.is_dir() else []),
            *self._matching("backups", _BACKUP_TEMP),
        ]
        return self._take(
            [p for p in found if _STORAGE_TEMP.match(p.name) or _BACKUP_TEMP.match(p.name)],
            before,
            dry_run,
        )

    def backups(self, before: datetime, dry_run: bool) -> Counted:
        found = self._matching("backups", _BACKUP)
        counted: Counted = (0, 0, 0)
        if found:
            newest = max(found, key=lambda p: p.stat().st_mtime)
            counted = self._take([p for p in found if p != newest], before, dry_run)
        if not dry_run:
            # Drop ledger entries whose file is gone, whether this run or an earlier one deleted
            # it (an earlier ledger update may have failed) (P11-007).
            self._reconcile_backups()
        return counted

    def app_logs(self, before: datetime, dry_run: bool) -> Counted:
        return self._take(self._matching("logs", _ROTATED), before, dry_run)

    # ---- internals -------------------------------------------------------------------------

    def _matching(self, name: str, pattern: re.Pattern[str]) -> list[Path]:
        folder = self._folders[name]
        if not folder.is_dir():
            return []
        return self._checked(name, (p for p in folder.iterdir() if pattern.match(p.name)))

    def _checked(self, name: str, paths: Iterable[Path]) -> list[Path]:
        """Only regular files (no links or junctions) whose real path stays in the folder."""
        folder = self._folders[name]
        kept: list[Path] = []
        for path in paths:
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                real = _real(path)
            except OSError:
                continue
            if folder in real.parents and real.parent == _real(path.parent):
                kept.append(path)
        return kept

    def _take(self, candidates: list[Path], before: datetime, dry_run: bool) -> Counted:
        limit = before.timestamp()
        items = size = failed = 0
        for path in candidates:
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime >= limit:
                continue
            if not dry_run:
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
                except OSError:
                    failed += 1  # held open or locked: tried again next time
                    continue
            items += 1
            size += stat.st_size
        return items, size, failed
