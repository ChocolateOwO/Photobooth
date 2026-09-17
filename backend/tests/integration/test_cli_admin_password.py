"""`photobooth admin-set-password`: stdin password, policy, head revision and instance lock."""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest

from photobooth.cli import main
from photobooth.core.instance_guard import InstanceLock
from tests.integration.test_cli import _init_env

PASSWORD = "a long enough admin password"


def _hash(root: Path) -> str:
    with sqlite3.connect(root / "data" / "db" / "photobooth.sqlite") as conn:
        return str(conn.execute("SELECT password_hash FROM admin_users").fetchone()[0])


def test_sets_and_changes_password_from_stdin(
    thai_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _init_env(thai_root)
    assert main(["db-upgrade", "--env-file", str(env)]) == 0
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    args = ["admin-set-password", "--env-file", str(env), "--password-stdin"]
    assert main([*args, "--expect-root", str(thai_root), "--expect-profile", "test"]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == {"username": "admin", "instance": "dummy"}
    assert PASSWORD not in out.out + out.err
    first = _hash(thai_root)
    assert first.startswith("$argon2id$")

    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + " changed\n"))
    assert main(args) == 0
    assert _hash(thai_root) != first


def test_powershell_bom_on_stdin_is_not_part_of_the_password(
    thai_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argon2 import PasswordHasher

    env = _init_env(thai_root)
    assert main(["db-upgrade", "--env-file", str(env)]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("﻿" + PASSWORD + "\r\n"))
    assert main(["admin-set-password", "--env-file", str(env), "--password-stdin"]) == 0
    assert PasswordHasher().verify(_hash(thai_root), PASSWORD)


def test_refuses_weak_password_and_wrong_intent(
    thai_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _init_env(thai_root)
    assert main(["db-upgrade", "--env-file", str(env)]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert main(["admin-set-password", "--env-file", str(env), "--password-stdin"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    wrong = ["--expect-profile", "prod"]
    assert main(["admin-set-password", "--env-file", str(env), "--password-stdin", *wrong]) == 2


def test_refuses_unmigrated_database_and_running_instance(
    thai_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _init_env(thai_root)
    args = ["admin-set-password", "--env-file", str(env), "--password-stdin"]
    assert main(["db-upgrade", "--env-file", str(env), "--revision", "0001_baseline"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    assert main(args) == 2

    assert main(["db-upgrade", "--env-file", str(env)]) == 0
    with InstanceLock(thai_root / "data" / "instance.lock"):
        monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
        assert main(args) == 2
