"""stop-dummy.ps1 kills only processes whose recorded identity matches exactly."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from helpers import SCRIPTS

MARKER = "-m photobooth serve --env-file"


def _start_sleeper(with_marker: bool) -> subprocess.Popen[bytes]:
    args = [sys.executable, "-c", "import time; time.sleep(120)"]
    if with_marker:
        args.append(MARKER)
    return subprocess.Popen(args)


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    # The venv python.exe is a launcher with a child interpreter: stop the whole tree.
    subprocess.run(
        ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False
    )
    proc.wait(timeout=30)


def _identity(proc: subprocess.Popen[bytes]) -> dict[str, object]:
    command = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        f"$p = Get-Process -Id {proc.pid}; "
        '$c = Get-CimInstance Win32_Process -Filter "ProcessId = ' + str(proc.pid) + '"; '
        "@{ start = $p.StartTime.ToUniversalTime().ToString('o'); exe = $c.ExecutablePath } "
        "| ConvertTo-Json"
    )
    for _ in range(50):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if data.get("exe"):
                return {"start_time": data["start"], "executable": data["exe"]}
        time.sleep(0.1)
    raise AssertionError("could not read process identity")


@pytest.fixture
def pid_file() -> Iterator[Path]:
    folder = Path(tempfile.mkdtemp(prefix="pb-stop-test-"))
    try:
        yield folder / "dummy-processes.json"
    finally:
        for item in folder.glob("*"):
            item.unlink()
        folder.rmdir()


def _write(pid_file: Path, entries: list[dict[str, object]]) -> None:
    record = {
        "instance": "dummy",
        "started_at": datetime.now(UTC).isoformat(),
        "processes": entries,
    }
    pid_file.write_text(json.dumps(record), encoding="utf-8")


def _stop(pid_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPTS / "stop-dummy.ps1"), "-PidFile", str(pid_file),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )  # fmt: skip


def test_refuses_unrelated_process_without_role_marker(pid_file: Path) -> None:
    proc = _start_sleeper(with_marker=False)
    try:
        ident = _identity(proc)
        _write(pid_file, [{"role": "backend", "pid": proc.pid, "marker": MARKER, **ident}])
        result = _stop(pid_file)
        assert result.returncode == 1
        assert proc.poll() is None, "unrelated process must survive"
        assert pid_file.exists()
    finally:
        _kill_tree(proc)


def test_recycled_pid_with_different_start_time_is_not_killed(pid_file: Path) -> None:
    proc = _start_sleeper(with_marker=True)
    try:
        ident = _identity(proc)
        ident["start_time"] = "2001-01-01T00:00:00.0000000Z"
        _write(pid_file, [{"role": "backend", "pid": proc.pid, "marker": MARKER, **ident}])
        result = _stop(pid_file)
        assert result.returncode == 0, result.stderr
        assert proc.poll() is None, "process with a different creation time must survive"
    finally:
        _kill_tree(proc)


def test_matching_identity_is_stopped_and_record_removed(pid_file: Path) -> None:
    proc = _start_sleeper(with_marker=True)
    ident = _identity(proc)
    _write(pid_file, [{"role": "backend", "pid": proc.pid, "marker": MARKER, **ident}])
    result = _stop(pid_file)
    assert result.returncode == 0, result.stdout + result.stderr
    assert proc.wait(timeout=30) is not None
    assert not pid_file.exists()
