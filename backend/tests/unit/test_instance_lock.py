from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from photobooth.core.errors import InstanceLockedError
from photobooth.core.instance_guard import InstanceLock

_TRY_LOCK = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from photobooth.core.instance_guard import InstanceLock
    from photobooth.core.errors import InstanceLockedError
    try:
        InstanceLock(Path(sys.argv[1])).acquire()
    except InstanceLockedError:
        sys.exit(17)
    sys.exit(0)
    """
)


def _other_process_lock(lock_path: Path) -> int:
    return subprocess.run(
        [sys.executable, "-c", _TRY_LOCK, str(lock_path)], check=False, timeout=60
    ).returncode


def test_second_process_cannot_acquire_lock(thai_root: Path) -> None:
    lock_path = thai_root / "data" / "instance.lock"
    with InstanceLock(lock_path) as lock:
        assert lock.held
        assert _other_process_lock(lock_path) == 17
    assert _other_process_lock(lock_path) == 0


def test_second_handle_in_same_process_is_rejected(thai_root: Path) -> None:
    lock_path = thai_root / "instance.lock"
    with InstanceLock(lock_path), pytest.raises(InstanceLockedError):
        InstanceLock(lock_path).acquire()


def test_lock_file_records_pid(thai_root: Path) -> None:
    import os

    lock_path = thai_root / "instance.lock"
    lock = InstanceLock(lock_path)
    lock.acquire()
    try:
        # Read through a separate handle without locking.
        assert lock_path.read_bytes().decode("ascii") == str(os.getpid())
    except PermissionError:
        pytest.fail("lock file must remain readable while locked")
    finally:
        lock.release()
    assert not lock.held
