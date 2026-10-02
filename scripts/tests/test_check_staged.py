"""Staged-content guard. Credential-like fixtures are assembled at runtime from fragments."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from helpers import APP_ROOT, SCRIPTS, git, new_repo, remove_tree

GUARD = SCRIPTS / "guards" / "check_staged.py"


def _pem_body() -> str:
    header = "-----BEGIN " + "PRIVATE KEY-----"
    footer = "-----END " + "PRIVATE KEY-----"
    return f"{header}\n{'QUJD' * 20}\n{'RUZH' * 20}\n{footer}\n"


def _client_secret_json() -> str:
    key_id, key_secret = '"client' + '_id"', '"client' + '_secret"'
    return (
        '{"installed": {'
        + key_id
        + ': "1234567890-abc.apps.example", '
        + key_secret
        + ': "GOCSPX-'
        + "a1b2c3d4e5f6g7h8"
        + '"}}'
    )


def _refresh_token() -> str:
    return "1/" + "/" + "0gAbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def _admin_password_assignment() -> str:
    return "PHOTOBOOTH_ADMIN_" + "PASSWORD=" + "hunter2" + "hunter2\n"


@pytest.fixture
def repo() -> Iterator[Path]:
    path = new_repo("guard")
    try:
        yield path
    finally:
        remove_tree(path)


def _stage(repo: Path, rel: str, content: str | bytes) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    git(repo, "add", "-f", "--", rel)


def _run(repo: Path, mode: str = "--staged") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), "--repo", str(repo), mode],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.parametrize(
    ("rel", "content", "rule"),
    [
        ("notes/key.txt", _pem_body(), "private-key"),
        ("config.json", _client_secret_json(), "client-secret"),
        ("drive/settings.txt", "refresh = " + _refresh_token(), "refresh-token"),
        ("deploy/admin.txt", _admin_password_assignment(), "secret-assignment"),
    ],
)
def test_populated_credentials_rejected(repo: Path, rel: str, content: str, rule: str) -> None:
    _stage(repo, rel, content)
    result = _run(repo)
    assert result.returncode == 1
    assert f"[{rule}]" in result.stderr


def test_env_example_with_empty_values_passes(repo: Path) -> None:
    _stage(repo, ".env.example", "PHOTOBOOTH_INSTANCE=dummy\nPHOTOBOOTH_ADMIN_PASSWORD=\n")
    result = _run(repo)
    assert result.returncode == 0, result.stderr


def test_client_secret_file_name_rejected_regardless_of_content(repo: Path) -> None:
    _stage(repo, "client_secret_x.json", "{}")
    result = _run(repo)
    assert result.returncode == 1
    assert "[sensitive-path]" in result.stderr


def test_large_file_rejected(repo: Path) -> None:
    _stage(repo, "big.txt", "a" * (5 * 1024 * 1024 + 1))
    result = _run(repo)
    assert result.returncode == 1
    assert "[size]" in result.stderr


def test_binary_outside_allowed_dirs_rejected_but_fixture_allowed(repo: Path) -> None:
    _stage(repo, "backend/tests/fixtures/ok.bin", b"\x00\x01\x02")
    assert _run(repo).returncode == 0
    _stage(repo, "src/blob.bin", b"\x00\x01\x02")
    result = _run(repo)
    assert result.returncode == 1
    assert "[binary]" in result.stderr


@pytest.mark.parametrize(
    "rel",
    [
        "backend/src/photobooth/frames_data/builtin/x.png",
        "backend/src/photobooth/stickers_data/builtin/x.png",
    ],
)
def test_packaged_builtin_images_are_allowed(repo: Path, rel: str) -> None:
    _stage(repo, rel, b"\x89PNG\r\n\x1a\n\x00\x00")
    assert _run(repo).returncode == 0


@pytest.mark.parametrize(
    "rel", ["data/db/photobooth.sqlite", "config/photobooth.env", "frontend/node_modules/x.js"]
)
def test_runtime_and_generated_paths_rejected(repo: Path, rel: str) -> None:
    _stage(repo, rel, "x")
    assert _run(repo).returncode == 1


def test_guard_its_patterns_and_tests_pass_the_guard(repo: Path) -> None:
    """The Phase 1 commit that contains the guard must itself pass the guard."""
    for source in (
        GUARD,
        Path(__file__),
        SCRIPTS / "tests" / "helpers.py",
        APP_ROOT / ".env.example",
    ):
        rel = source.relative_to(APP_ROOT).as_posix()
        _stage(repo, rel, source.read_bytes())
    result = _run(repo)
    assert result.returncode == 0, result.stderr


def test_tracked_mode_scans_current_repository() -> None:
    result = _run(APP_ROOT, "--tracked")
    assert result.returncode == 0, result.stderr
