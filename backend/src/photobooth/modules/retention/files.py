"""This instance's own files that retention may delete: temporary files, backups, rotated logs.

Every folder must lie inside the instance root, and every file is taken only when its real path
(after links and junctions) is still inside its folder, so a cleanup can never reach Main, another
instance or anything else on the machine. Nothing is followed into subfolders except the storage
folder's own tree for temporary files.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from photobooth.modules.retention.domain import RetentionError

# A temporary file the storage writes before it moves a photo into place (left by a crash).
_TEMP = re.compile(r"^\..+\.[0-9a-f]{12}\.tmp$")
# Backups made by the backup command: <instance>-<stamp>-<revision>.sqlite
_BACKUP = re.compile(r"^[a-z]+-.+\.sqlite$")
# Rotated application logs (photobooth.log.1 ...) and launcher logs; never the log being written.
_ROTATED = re.compile(r"^[A-Za-z0-9_.-]+\.log(\.\d+)?$")
_CURRENT_LOG = "photobooth.log"


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
        forget_backups: Callable[[set[str]], None],
    ) -> None:
        self._forget_backups = forget_backups
        root = _real(instance_root)
        self._folders: dict[str, Path] = {}
        for name, folder in (("storage", storage), ("backups", backups), ("logs", logs)):
            real = _real(folder)
            if real == root or root not in real.parents:
                raise RetentionError(f"the {name} folder is not inside this instance")
            self._folders[name] = real

    # ---- the port --------------------------------------------------------------------------

    def temp(self, before: datetime, dry_run: bool) -> tuple[int, int]:
        folder = self._folders["storage"]
        found = [p for p in folder.rglob("*.tmp") if _TEMP.match(p.name)] if folder.is_dir() else []
        return self._take("storage", found, before, dry_run)

    def backups(self, before: datetime, dry_run: bool) -> tuple[int, int]:
        found = self._files("backups", _BACKUP)
        if not found:
            return 0, 0
        newest = max(found, key=lambda p: p.stat().st_mtime)
        older = [p for p in found if p != newest]  # the newest backup always stays
        counted = self._take("backups", older, before, dry_run)
        if counted[0] and not dry_run:
            self._forget_backups({p.name for p in older if not p.exists()})
        return counted

    def app_logs(self, before: datetime, dry_run: bool) -> tuple[int, int]:
        found = [p for p in self._files("logs", _ROTATED) if p.name != _CURRENT_LOG]
        return self._take("logs", found, before, dry_run)

    # ---- internals -------------------------------------------------------------------------

    def _files(self, name: str, pattern: re.Pattern[str]) -> list[Path]:
        folder = self._folders[name]
        if not folder.is_dir():
            return []
        return [p for p in folder.iterdir() if p.is_file() and pattern.match(p.name)]

    def _take(
        self, name: str, candidates: list[Path], before: datetime, dry_run: bool
    ) -> tuple[int, int]:
        folder = self._folders[name]
        limit = before.timestamp()
        items = size = 0
        for path in candidates:
            real = _real(path)
            if folder not in real.parents or path.is_symlink():
                continue  # never anything that leads outside this folder
            stat = path.stat()
            if stat.st_mtime >= limit:
                continue
            if not dry_run:
                path.unlink(missing_ok=True)
            items += 1
            size += stat.st_size
        return items, size
