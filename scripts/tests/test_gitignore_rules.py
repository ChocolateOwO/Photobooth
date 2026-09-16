"""The committed .gitignore must ignore runtime/secret paths and must NOT ignore source modules."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from helpers import APP_ROOT, new_repo, remove_tree

MUST_IGNORE = [
    "data/db/x.sqlite",
    "config/photobooth.env",
    "backend/.env",
    "client_secret_1.json",
    "node_modules/a/index.js",
    "x.sqlite-wal",
    "backend/.venv/Scripts/python.exe",
    "frontend/dist/index.html",
    "credentials.json",
    "token.json",
    "server.pem",
    "backups/dummy.sqlite",
    "logs/photobooth.log",
    "storage/captures/a.jpg",
    "frontend/.env.local",
    "e2e/playwright-report/index.html",
    "backend/photobooth.egg-info/PKG-INFO",
]

MUST_NOT_IGNORE = [
    ".env.example",
    "backend/src/photobooth/modules/storage/service.py",
    "backend/src/photobooth/modules/captures/service.py",
    "backend/src/photobooth/modules/outputs/service.py",
    "frontend/src/features/capture/x.tsx",
    "backend/src/photobooth/core/config.py",
    "backend/tests/fixtures/sample.png",
    "scripts/verify.ps1",
]


@pytest.fixture
def repo_with_rules() -> Iterator[Path]:
    repo = new_repo("gitignore")
    shutil.copyfile(APP_ROOT / ".gitignore", repo / ".gitignore")
    try:
        yield repo
    finally:
        remove_tree(repo)


def _check_ignore(repo: Path, rel: str) -> bool:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    result = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", "--no-index", "--", rel], check=False
    )
    return result.returncode == 0


def test_gitignore_has_one_pattern_per_line() -> None:
    for line in (APP_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            assert " " not in line.strip(), f"multiple patterns on one line: {line!r}"


@pytest.mark.parametrize("rel", MUST_IGNORE)
def test_sensitive_paths_are_ignored(repo_with_rules: Path, rel: str) -> None:
    assert _check_ignore(repo_with_rules, rel), rel


@pytest.mark.parametrize("rel", MUST_NOT_IGNORE)
def test_source_paths_are_not_ignored(repo_with_rules: Path, rel: str) -> None:
    assert not _check_ignore(repo_with_rules, rel), rel
