from __future__ import annotations

from pathlib import Path

import pytest

from photobooth.core.config import AppSettings
from photobooth.core.errors import ConfigurationError


def _write_env(path: Path, root: Path, extra: str = "") -> Path:
    path.write_text(
        "\n".join(
            [
                "PHOTOBOOTH_INSTANCE=dummy",
                "PHOTOBOOTH_PROFILE=test",
                f"PHOTOBOOTH_INSTANCE_ROOT={root}",
                "PHOTOBOOTH_KIOSK_PORT=18111",
                "PHOTOBOOTH_DELIVERY_PORT=18113",
                extra,
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_loads_env_file_from_thai_path(thai_root: Path) -> None:
    (thai_root / "config").mkdir()
    env = _write_env(thai_root / "config" / "photobooth.env", thai_root)
    settings = AppSettings.from_env_file(env)

    assert settings.instance == "dummy"
    assert settings.instance_root == thai_root
    assert "ทดสอบ" in str(settings.db_path)
    assert settings.db_path == thai_root / "data" / "db" / "photobooth.sqlite"
    assert settings.runtime_dir == thai_root / "config" / "runtime"
    assert settings.device_cookie_name == "pb_device_dummy"


def test_relative_paths_resolve_against_instance_root(thai_root: Path) -> None:
    env = _write_env(thai_root / "a.env", thai_root, "PHOTOBOOTH_STORAGE_DIR=data/other")
    settings = AppSettings.from_env_file(env)
    assert settings.storage_dir == thai_root / "data" / "other"


def test_missing_env_file_is_configuration_error(thai_root: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        AppSettings.from_env_file(thai_root / "missing.env")


def test_unknown_instance_rejected(thai_root: Path) -> None:
    env = _write_env(thai_root / "b.env", thai_root)
    env.write_text(env.read_text(encoding="utf-8").replace("=dummy", "=staging"), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        AppSettings.from_env_file(env)


def test_relative_instance_root_rejected(thai_root: Path) -> None:
    env = thai_root / "c.env"
    env.write_text(
        "PHOTOBOOTH_INSTANCE=dummy\nPHOTOBOOTH_INSTANCE_ROOT=relative\n"
        "PHOTOBOOTH_KIOSK_PORT=1\nPHOTOBOOTH_DELIVERY_PORT=2\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="absolute"):
        AppSettings.from_env_file(env)
