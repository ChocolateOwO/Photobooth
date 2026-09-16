"""CLI flows used by run-dummy.ps1 / e2e.ps1, exercised in a Thai-character temp instance."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from photobooth.cli import main
from photobooth.core.instance_guard import InstanceLock


def _init_env(root: Path, instance: str = "dummy") -> Path:
    env = root / "config" / "photobooth.env"
    code = main(
        [
            "init-env",
            "--instance",
            instance,
            "--profile",
            "test",
            "--instance-root",
            str(root),
            "--output",
            str(env),
            "--kiosk-port",
            "18111",
            "--delivery-port",
            "18113",
            "--delivery-host",
            "127.0.0.1",
        ]
    )
    assert code == 0
    return env


def test_init_env_upgrade_check_and_backup(
    thai_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _init_env(thai_root)
    assert "ทดสอบ" in env.read_text(encoding="utf-8")

    assert main(["db-upgrade", "--env-file", str(env)]) == 0
    assert main(["db-check", "--env-file", str(env)]) == 0
    capsys.readouterr()
    assert main(["backup", "--env-file", str(env)]) == 0
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["integrity"] == "ok"
    assert Path(record["path"]).parent == thai_root / "data" / "backups"


def test_init_env_refuses_overwrite(thai_root: Path) -> None:
    env = _init_env(thai_root)
    assert (
        main(
            [
                "init-env",
                "--instance",
                "dummy",
                "--profile",
                "test",
                "--instance-root",
                str(thai_root),
                "--output",
                str(env),
                "--kiosk-port",
                "1",
                "--delivery-port",
                "2",
            ]
        )
        == 2
    )


def test_db_upgrade_refuses_database_of_other_instance(thai_root: Path) -> None:
    env = _init_env(thai_root)
    assert main(["db-upgrade", "--env-file", str(env)]) == 0
    db = thai_root / "data" / "db" / "photobooth.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE app_meta SET value='main' WHERE key='instance'")
    assert main(["db-upgrade", "--env-file", str(env)]) == 2
    assert main(["db-check", "--env-file", str(env)]) == 2


def test_db_check_fails_before_migration(thai_root: Path) -> None:
    env = _init_env(thai_root)
    assert main(["db-check", "--env-file", str(env)]) == 2


def test_serve_refuses_when_instance_lock_is_held(thai_root: Path) -> None:
    env = _init_env(thai_root)
    assert main(["db-upgrade", "--env-file", str(env)]) == 0
    with InstanceLock(thai_root / "data" / "instance.lock"):
        assert main(["serve", "--env-file", str(env)]) == 2


def test_guard_failure_exits_nonzero(thai_root: Path) -> None:
    env = _init_env(thai_root)
    text = env.read_text(encoding="utf-8").replace(
        "PHOTOBOOTH_KIOSK_HOST=127.0.0.1", "PHOTOBOOTH_KIOSK_HOST=0.0.0.0"
    )
    env.write_text(text, encoding="utf-8")
    assert main(["db-upgrade", "--env-file", str(env)]) == 2
