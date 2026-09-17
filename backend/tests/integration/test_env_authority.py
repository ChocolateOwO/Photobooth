"""Explicit env file is authoritative: inherited PHOTOBOOTH_* variables never redirect work."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from photobooth.cli import main
from photobooth.core.config import AppSettings


def _init_env(root: Path, profile: str = "test") -> Path:
    env = root / "config" / "photobooth.env"
    args = [
        "init-env", "--instance", "dummy", "--profile", profile, "--instance-root", str(root),
        "--output", str(env), "--kiosk-port", "18111", "--delivery-port", "18113",
        "--delivery-host", "127.0.0.1",
    ]  # fmt: skip
    assert main(args) == 0
    return env


HOSTILE = {
    "PHOTOBOOTH_INSTANCE": "main",
    "PHOTOBOOTH_PROFILE": "prod",
    "PHOTOBOOTH_KIOSK_PORT": "8111",
    "PHOTOBOOTH_DELIVERY_PORT": "8113",
    "PHOTOBOOTH_KIOSK_HOST": "0.0.0.0",
}


def test_environment_variables_do_not_override_env_file(
    thai_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _init_env(thai_root)
    victim_root = thai_root.parent / f"{thai_root.name}-real-dummy"
    for key, value in {
        **HOSTILE,
        "PHOTOBOOTH_INSTANCE_ROOT": str(victim_root),
        "PHOTOBOOTH_DB_PATH": str(victim_root / "data" / "db" / "photobooth.sqlite"),
    }.items():
        monkeypatch.setenv(key, value)

    settings = AppSettings.from_env_file(env)
    assert settings.instance == "dummy"
    assert settings.profile == "test"
    assert settings.instance_root == thai_root
    assert settings.db_path == thai_root / "data" / "db" / "photobooth.sqlite"
    assert settings.kiosk_port == 18111
    assert settings.kiosk_host == "127.0.0.1"


def test_migration_subprocess_with_inherited_dev_settings_touches_only_its_file(
    thai_root: Path,
) -> None:
    env = _init_env(thai_root)
    victim_root = thai_root.parent / f"{thai_root.name}-inherited"
    victim_db = victim_root / "data" / "db" / "photobooth.sqlite"
    child_env = {
        **os.environ,
        **HOSTILE,
        "PHOTOBOOTH_INSTANCE_ROOT": str(victim_root),
        "PHOTOBOOTH_DB_PATH": str(victim_db),
    }
    result = subprocess.run(
        [sys.executable, "-m", "photobooth", "db-upgrade", "--env-file", str(env)],
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not victim_db.exists()
    assert not victim_root.exists()
    with sqlite3.connect(thai_root / "data" / "db" / "photobooth.sqlite") as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key='instance'").fetchone()
    assert row == ("dummy",)


def test_git_commit_is_the_only_value_taken_from_the_caller(thai_root: Path) -> None:
    env = _init_env(thai_root)
    settings = AppSettings.from_env_file(env, git_commit="abc123")
    assert settings.git_commit == "abc123"


def test_launcher_intent_mismatch_refuses_before_mutation(thai_root: Path) -> None:
    env = _init_env(thai_root)
    db = thai_root / "data" / "db" / "photobooth.sqlite"
    other = thai_root.parent / "somewhere-else"
    assert main(["db-upgrade", "--env-file", str(env), "--expect-root", str(other)]) == 2
    assert not db.exists()
    assert main(["db-upgrade", "--env-file", str(env), "--expect-profile", "e2e"]) == 2
    assert not db.exists()
    assert (
        main(
            [
                "db-upgrade",
                "--env-file",
                str(env),
                "--expect-root",
                str(thai_root),
                "--expect-profile",
                "test",
            ]
        )
        == 0
    )
    assert db.exists()


def test_allowed_origins_are_exact_instance_ports(thai_root: Path) -> None:
    env = _init_env(thai_root)
    text = env.read_text(encoding="utf-8") + "PHOTOBOOTH_UI_PORT=18191\n"
    env.write_text(text, encoding="utf-8")
    settings = AppSettings.from_env_file(env)
    assert settings.allowed_origins == frozenset(
        {
            "http://127.0.0.1:18111",
            "http://localhost:18111",
            "http://127.0.0.1:18191",
            "http://localhost:18191",
        }
    )
