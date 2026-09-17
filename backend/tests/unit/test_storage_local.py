"""StorageKey validation and LocalStorageProvider containment (traversal, junctions, overwrite)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from photobooth.modules.storage.domain import InvalidStorageKeyError, StorageError, StorageKey
from photobooth.modules.storage.local import LocalStorageProvider


def _junction(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../escape.png",
        "assets/../../escape.png",
        "assets/./logo.png",
        "..",
        "/abs/logo.png",
        "C:/Windows/logo.png",
        "c:",
        "assets\\logo.png",
        "assets//logo.png",
        "assets/.hidden",
        "Assets/logo.png",
        "assets/logo.png/",
        "assets/lo go.png",
        "assets/logo.png:stream",
        "assets/โลโก้.png",
        "a/b/c/d/e/f/g/h/i.png",
        "x" * 256,
    ],
)
def test_unsafe_keys_are_rejected(key: str) -> None:
    with pytest.raises(InvalidStorageKeyError):
        StorageKey(key)


def test_put_get_round_trip_is_atomic_and_idempotent(thai_root: Path) -> None:
    storage = LocalStorageProvider(thai_root / "storage")
    key = StorageKey("assets/logo/ab/abcdef.png")
    storage.put(key, b"one")
    storage.put(key, b"one")  # identical content: kept
    assert storage.get(key) == b"one"
    assert storage.exists(key)
    assert not list((thai_root / "storage").rglob("*.tmp"))
    with pytest.raises(StorageError):
        storage.put(key, b"two")  # different content is never silently overwritten
    assert storage.get(key) == b"one"
    storage.delete(key)
    storage.delete(key)
    assert not storage.exists(key)
    with pytest.raises(StorageError):
        storage.get(key)


def test_junction_inside_storage_can_not_redirect_writes(thai_root: Path) -> None:
    outside = thai_root / "Main" / "storage"
    outside.mkdir(parents=True)
    root = thai_root / "storage"
    root.mkdir()
    _junction(root / "assets", outside)
    storage = LocalStorageProvider(root)
    key = StorageKey("assets/logo/ab/abcdef.png")
    with pytest.raises(InvalidStorageKeyError):
        storage.put(key, b"data")
    with pytest.raises(InvalidStorageKeyError):
        storage.get(key)
    assert not any(outside.rglob("*"))
