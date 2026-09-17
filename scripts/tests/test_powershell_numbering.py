"""verify.ps1 milestone numbering, executed by Windows PowerShell (not re-implemented)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from helpers import SCRIPTS, commit_file, git, new_repo, remove_tree


@pytest.fixture
def repo() -> Iterator[Path]:
    path = new_repo("numbering")
    commit_file(path, "a.txt", "a", "first")
    try:
        yield path
    finally:
        remove_tree(path)


def _next_number(repo: Path) -> str:
    common = str(SCRIPTS / "lib" / "common.ps1").replace("'", "''")
    target = str(repo).replace("'", "''")
    command = f". '{common}'; Get-NextMilestoneNumber -Repo '{target}'"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_no_tags_gives_001(repo: Path) -> None:
    assert _next_number(repo) == "001"


def test_existing_tag_gives_next_integer(repo: Path) -> None:
    git(repo, "tag", "-a", "dummy-patch-001-project-foundation", "-m", "x")
    assert _next_number(repo) == "002"


def test_highest_tag_wins_and_other_tags_ignored(repo: Path) -> None:
    for tag in ("dummy-patch-001-a", "dummy-patch-009-b", "main-release-042", "checkpoint-010-x"):
        git(repo, "tag", "-a", tag, "-m", "x")
    assert _next_number(repo) == "010"
