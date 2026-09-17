"""One canonical lock per instance root, whatever data paths are configured."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from photobooth.cli import main
from photobooth.core.instance_guard import InstanceLock
from tests.conftest import make_settings


def test_lock_path_ignores_data_dir_override(thai_root: Path) -> None:
    default = make_settings(thai_root)
    overridden = make_settings(thai_root, data_dir=Path("data2"), logs_dir=Path("data2/logs"))
    assert default.lock_path == overridden.lock_path == thai_root / "data" / "instance.lock"


def test_second_invocation_with_other_data_dir_cannot_migrate_live_instance(
    thai_root: Path,
) -> None:
    env = thai_root / "config" / "photobooth.env"
    args = [
        "init-env", "--instance", "dummy", "--profile", "test", "--instance-root", str(thai_root),
        "--output", str(env), "--kiosk-port", "18111", "--delivery-port", "18113",
        "--delivery-host", "127.0.0.1",
    ]  # fmt: skip
    assert main(args) == 0
    assert main(["db-upgrade", "--env-file", str(env)]) == 0

    alternate = thai_root / "config" / "alternate.env"
    alternate.write_text(
        env.read_text(encoding="utf-8") + "PHOTOBOOTH_DATA_DIR=data2\n", encoding="utf-8"
    )
    runtime_token = thai_root / "config" / "runtime" / "launcher.token"
    runtime_token.parent.mkdir(parents=True, exist_ok=True)
    runtime_token.write_text("live-server-token", encoding="utf-8")

    db = thai_root / "data" / "db" / "photobooth.sqlite"
    with InstanceLock(thai_root / "data" / "instance.lock"):  # the running server
        assert main(["db-downgrade", "--env-file", str(alternate), "--revision", "base"]) == 2
        assert main(["db-upgrade", "--env-file", str(alternate)]) == 2

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='app_meta'").fetchone()
    assert runtime_token.read_text(encoding="utf-8") == "live-server-token"
