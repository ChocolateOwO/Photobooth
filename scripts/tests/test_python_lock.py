"""Backend dependency lock: committed lock matches the environment; drift is always detected."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from helpers import APP_ROOT, SCRIPTS

BACKEND = APP_ROOT / "backend"
TOOL = SCRIPTS / "guards" / "python_lock.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("python_lock_under_test", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _check(
    lock: Path, pyproject: Path = BACKEND / "pyproject.toml"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "check", "--pyproject", str(pyproject), "--lock", str(lock)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_committed_lock_matches_the_backend_environment() -> None:
    result = _check(BACKEND / "requirements-dev.lock")
    assert result.returncode == 0, result.stderr


def test_committed_lock_pins_runtime_dev_and_build_dependencies() -> None:
    tool = _tool()
    pins = tool.parse_lock((BACKEND / "requirements-dev.lock").read_text(encoding="utf-8"))
    for name in ("fastapi", "sqlalchemy", "alembic", "pytest", "mypy", "ruff", "setuptools"):
        assert name in pins, name
    assert "photobooth" not in pins and "pip" not in pins


def test_version_drift_in_lock_is_rejected(tmp_path: Path) -> None:
    lines = (BACKEND / "requirements-dev.lock").read_text(encoding="utf-8").splitlines()
    changed = [("fastapi==0.0.1" if line.startswith("fastapi==") else line) for line in lines]
    lock = tmp_path / "drift.lock"
    lock.write_text("\n".join(changed) + "\n", encoding="utf-8")
    result = _check(lock)
    assert result.returncode == 1
    assert "version drift: fastapi" in result.stderr


def test_missing_and_unlocked_packages_are_rejected(tmp_path: Path) -> None:
    lines = (BACKEND / "requirements-dev.lock").read_text(encoding="utf-8").splitlines()
    lock = tmp_path / "missing.lock"
    lock.write_text(
        "\n".join(line for line in lines if not line.startswith("uvicorn==")) + "\nnotreal==1.0\n",
        encoding="utf-8",
    )
    result = _check(lock)
    assert result.returncode == 1
    assert "not in lock: uvicorn" in result.stderr
    assert "missing from environment: notreal==1.0" in result.stderr


def test_compare_reports_extraneous_installed_packages() -> None:
    tool = _tool()
    problems = tool.compare({"a": "1"}, {"a": "1"}, ["left-behind-tool"])
    assert problems == ["extraneous installed package: left-behind-tool"]


def test_lock_must_contain_exact_pins_only() -> None:
    tool = _tool()
    with pytest.raises(tool.LockError, match="exact pin"):
        tool.parse_lock("fastapi>=0.100\n")


def test_pyproject_requirements_must_be_satisfied_by_lock() -> None:
    tool = _tool()
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    pins = tool.parse_lock((BACKEND / "requirements-dev.lock").read_text(encoding="utf-8"))
    assert tool.unsatisfied_pyproject(pyproject, pins) == []
    older = {**pins, "sqlalchemy": "1.4.0"}
    assert any("sqlalchemy" in p for p in tool.unsatisfied_pyproject(pyproject, older))
    without = {k: v for k, v in pins.items() if k != "alembic"}
    assert any("not locked: alembic" in p for p in tool.unsatisfied_pyproject(pyproject, without))
