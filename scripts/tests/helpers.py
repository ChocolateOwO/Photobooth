"""Throwaway git repositories under the system temp dir (never inside Photobooth)."""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = APP_ROOT / "scripts"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, f"git {args}: {result.stderr}"
    return result.stdout.strip()


def new_repo(label: str) -> Path:
    root = Path(tempfile.gettempdir()) / f"pb-ทดลอง-{label}-{secrets.token_hex(4)}"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "dummy")
    git(root, "config", "user.name", "photobooth-test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "tag.gpgsign", "false")
    return root


def commit_file(repo: Path, rel: str, content: str | bytes, message: str) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "--", rel)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def remove_tree(path: Path) -> None:
    def onexc(func, p, _exc):  # type: ignore[no-untyped-def]
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if path.exists():
        shutil.rmtree(path, onexc=onexc)
