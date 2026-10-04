"""Startup safety checks that keep Dummy and Main isolated.

The server refuses to start when any check fails. Checks are pure functions of the
settings plus a database probe, so each one is unit-testable.
"""

from __future__ import annotations

import ipaddress
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Protocol

from photobooth.core.config import AppSettings
from photobooth.core.errors import InstanceGuardError, InstanceLockedError


@dataclass(frozen=True)
class PortPair:
    kiosk: int
    delivery: int
    ui: int | None = None


# (instance, profile) -> fixed ports. `test` profile uses ephemeral ports inside a temp root.
PORT_TABLE: dict[tuple[str, str], PortPair] = {
    ("dummy", "dev"): PortPair(kiosk=8111, delivery=8113, ui=5191),
    ("dummy", "e2e"): PortPair(kiosk=8112, delivery=8114, ui=5192),
    ("main", "prod"): PortPair(kiosk=8121, delivery=8123, ui=None),
}

ALLOWED_PROFILES: dict[str, frozenset[str]] = {
    "dummy": frozenset({"dev", "e2e", "test"}),
    "main": frozenset({"prod", "test"}),
}

TEMP_ROOT_PROFILES = frozenset({"e2e", "test"})


class AppMetaReader(Protocol):
    """Reads the instance stamp stored in the database (`app_meta.instance`)."""

    def read_instance(self) -> str | None: ...


def real_path(path: Path) -> Path:
    """Resolve symlinks and NTFS junctions, even for paths that do not exist yet."""
    return Path(os.path.realpath(path))


def is_within(child: Path, parent: Path) -> bool:
    child_real = real_path(child)
    parent_real = real_path(parent)
    return child_real == parent_real or parent_real in child_real.parents


class InstanceGuard:
    """Validates that an instance's settings cannot touch another instance."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def check_static(self) -> None:
        """All checks that need no database. Raises InstanceGuardError on first failure."""
        self.check_profile()
        self.check_root()
        self.check_paths()
        self.check_ports()
        self.check_bind_addresses()

    def check_profile(self) -> None:
        s = self._settings
        if s.profile not in ALLOWED_PROFILES[s.instance]:
            raise InstanceGuardError(
                "profile", f"profile '{s.profile}' is not allowed for instance '{s.instance}'"
            )

    def check_root(self) -> None:
        s = self._settings
        root = real_path(s.instance_root)
        if s.profile in TEMP_ROOT_PROFILES:
            if not is_within(root, Path(tempfile.gettempdir())):
                raise InstanceGuardError(
                    "instance_root", f"{s.profile} instances must live under the system temp dir"
                )
        elif root.name.lower() != s.instance:
            raise InstanceGuardError(
                "instance_root",
                f"instance root folder '{root.name}' does not match instance '{s.instance}'",
            )

    def check_paths(self) -> None:
        s = self._settings
        named = {
            "data_dir": s.data_dir,
            "db_path": s.db_path,
            "storage_dir": s.storage_dir,
            "backups_dir": s.backups_dir,
            "logs_dir": s.logs_dir,
            "config_dir": s.config_dir,
            # Derived paths the process mutates: validated separately so a nested junction or
            # file link below an otherwise-contained directory cannot redirect writes.
            "runtime_dir": s.runtime_dir,
            "pairing_code": s.runtime_dir / "pairing.code",
            "launcher_token": s.runtime_dir / "launcher.token",
            "lock_path": s.lock_path,
            "db_wal": s.db_path.with_name(s.db_path.name + "-wal"),
            "db_shm": s.db_path.with_name(s.db_path.name + "-shm"),
            "log_file": s.logs_dir / "photobooth.log",
            "backup_ledger": s.backups_dir / "BACKUPS.json",
        }
        for name, path in named.items():
            if not is_within(path, s.instance_root):
                raise InstanceGuardError(
                    "path_containment",
                    f"{name} resolves outside instance root: {real_path(path)}",
                )

    def check_ports(self) -> None:
        s = self._settings
        if s.kiosk_port == s.delivery_port:
            raise InstanceGuardError("ports", "kiosk and delivery ports must differ")
        if s.screen_port is not None and s.screen_port in (
            s.kiosk_port,
            s.delivery_port,
            s.ui_port,
        ):
            raise InstanceGuardError("ports", "the TV screen port must differ from the others")
        expected = PORT_TABLE.get((s.instance, s.profile))
        if expected is None:
            return  # test profile: ephemeral ports, root already confined to temp dir
        actual = (s.kiosk_port, s.delivery_port, s.ui_port)
        if actual != (expected.kiosk, expected.delivery, expected.ui):
            raise InstanceGuardError(
                "ports",
                f"{s.instance}/{s.profile} must use kiosk {expected.kiosk}, delivery "
                f"{expected.delivery}, ui {expected.ui}; got {actual[0]}/{actual[1]}/{actual[2]}",
            )

    def check_bind_addresses(self) -> None:
        s = self._settings
        try:
            kiosk = ipaddress.ip_address(s.kiosk_host)
        except ValueError as exc:
            raise InstanceGuardError(
                "bind", f"kiosk host must be a loopback IP literal, got '{s.kiosk_host}'"
            ) from exc
        if not kiosk.is_loopback:
            raise InstanceGuardError("bind", f"kiosk listener must be loopback, got {kiosk}")
        try:
            ipaddress.ip_address(s.delivery_host)
        except ValueError as exc:
            raise InstanceGuardError(
                "bind", f"delivery host must be an IP literal, got '{s.delivery_host}'"
            ) from exc

    def check_database(self, meta: AppMetaReader) -> None:
        stamped = meta.read_instance()
        if stamped is None:
            raise InstanceGuardError(
                "database", "database has no instance stamp; run 'photobooth db-upgrade' first"
            )
        if stamped != self._settings.instance:
            raise InstanceGuardError(
                "database",
                f"database belongs to instance '{stamped}', not '{self._settings.instance}'",
            )


class InstanceLock:
    """Exclusive OS-level lock file: one backend process per instance.

    The locked byte lies far beyond the PID text, so the PID stays readable by other processes.
    """

    LOCK_OFFSET = 0x10000

    def __init__(self, lock_path: Path) -> None:
        self._path = lock_path
        self._handle: IO[bytes] | None = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+b")  # noqa: SIM115 - held open for process lifetime
        try:
            self._lock(handle)
        except OSError as exc:
            handle.close()
            raise InstanceLockedError(str(self._path)) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    @staticmethod
    def _lock(handle: IO[bytes]) -> None:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(InstanceLock.LOCK_OFFSET)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle: IO[bytes]) -> None:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(InstanceLock.LOCK_OFFSET)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
