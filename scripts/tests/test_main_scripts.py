"""Main scripts: the first-install refusals that happen before anything is written, the Main
launcher's layout check, and stop-main.ps1 stopping only a matching recorded process.

Nothing here creates or touches the real Main folder: every refusal is reached before any write,
and the folders used live under the system temp dir.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_stop_dummy import MARKER, _identity, _kill_tree

from helpers import APP_ROOT, SCRIPTS, git, remove_tree

REAL_MAIN = APP_ROOT.parent.parent / "Main"


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPTS / script), *args,
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )  # fmt: skip


@pytest.fixture
def temp_base() -> Iterator[Path]:
    base = Path(tempfile.mkdtemp(prefix="pb-main-test-"))
    try:
        yield base
    finally:
        remove_tree(base)


@pytest.fixture(autouse=True)
def _never_the_real_main() -> Iterator[None]:
    existed = REAL_MAIN.exists()
    yield
    assert REAL_MAIN.exists() == existed, "a test changed the real Main folder"


def _head() -> str:
    return git(APP_ROOT, "rev-parse", "HEAD")


def test_a_rehearsal_only_goes_under_the_temp_dir() -> None:
    target = Path(APP_ROOT.anchor) / "pb-not-temp-for-test" / "Main"
    result = _run("install-main.ps1", "-Commit", _head(), "-Rehearsal", "-MainRoot", str(target))
    assert result.returncode != 0
    assert "goes under" in result.stdout + result.stderr
    assert not target.parent.exists()


def test_the_folder_must_be_named_main(temp_base: Path) -> None:
    target = temp_base / "Mainx"
    result = _run("install-main.ps1", "-Commit", _head(), "-Rehearsal", "-MainRoot", str(target))
    assert result.returncode != 0
    assert "must be named Main" in result.stdout + result.stderr
    assert not target.exists()


def test_a_folder_that_is_not_empty_is_refused(temp_base: Path) -> None:
    target = temp_base / "Main"
    target.mkdir()
    (target / "keep.txt").write_text("mine", encoding="utf-8")
    result = _run("install-main.ps1", "-Commit", _head(), "-Rehearsal", "-MainRoot", str(target))
    assert result.returncode != 0
    assert "not empty" in result.stdout + result.stderr
    assert [p.name for p in target.iterdir()] == ["keep.txt"]


def test_an_unknown_commit_is_refused(temp_base: Path) -> None:
    target = temp_base / "Main"
    result = _run("install-main.ps1", "-Commit", "0" * 40, "-Rehearsal", "-MainRoot", str(target))
    assert result.returncode != 0
    assert "is not in" in result.stdout + result.stderr
    assert not target.exists()


def test_the_real_install_needs_an_approved_tag() -> None:
    # Refused while checking its arguments, before the real Main path is looked at on disk.
    result = _run("install-main.ps1", "-Commit", _head())
    assert result.returncode != 0
    assert "needs -Tag" in result.stdout + result.stderr


def test_the_main_launcher_refuses_to_run_from_the_dummy_checkout() -> None:
    result = _run("run-main.ps1", "-NoBrowser")
    assert result.returncode != 0
    assert "expected <project>\\Main\\app layout" in result.stdout + result.stderr


def test_stop_main_stops_a_matching_recorded_process(temp_base: Path) -> None:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", MARKER])
    pid_file = temp_base / "main-processes.json"
    try:
        ident = _identity(proc)
        record = {
            "instance": "main",
            "processes": [{"role": "backend", "pid": proc.pid, "marker": MARKER, **ident}],
        }
        pid_file.write_text(json.dumps(record), encoding="utf-8")
        result = _run("stop-main.ps1", "-PidFile", str(pid_file))
        assert result.returncode == 0, result.stdout + result.stderr
        assert proc.wait(timeout=30) is not None
        assert not pid_file.exists()
    finally:
        if proc.poll() is None:
            _kill_tree(proc)
