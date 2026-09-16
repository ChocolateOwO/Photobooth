"""Derived paths (runtime secrets, lock, logs) must not escape through nested junctions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from photobooth.core.errors import InstanceGuardError
from photobooth.core.instance_guard import InstanceGuard
from tests.conftest import make_settings


def _junction(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)


def _assert_containment_failure(root: Path) -> None:
    with pytest.raises(InstanceGuardError) as info:
        InstanceGuard(make_settings(root)).check_static()
    assert info.value.check == "path_containment"


def test_rejects_nested_runtime_junction_and_leaves_target_untouched(thai_root: Path) -> None:
    root = thai_root / "instance"
    foreign_runtime = thai_root / "Main" / "config" / "runtime"
    foreign_runtime.mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    victim = foreign_runtime / "pairing.code"
    victim.write_text("main-code", encoding="utf-8")
    _junction(root / "config" / "runtime", foreign_runtime)

    _assert_containment_failure(root)
    assert victim.read_text(encoding="utf-8") == "main-code"


def test_rejects_junctioned_logs_directory(thai_root: Path) -> None:
    root = thai_root / "instance"
    outside = thai_root / "elsewhere-logs"
    outside.mkdir()
    (root / "data").mkdir(parents=True)
    _junction(root / "data" / "logs", outside)
    _assert_containment_failure(root)


def test_rejects_junctioned_backups_directory(thai_root: Path) -> None:
    root = thai_root / "instance"
    outside = thai_root / "elsewhere-backups"
    outside.mkdir()
    (root / "data").mkdir(parents=True)
    _junction(root / "data" / "backups", outside)
    _assert_containment_failure(root)
