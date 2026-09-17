"""PowerShell launcher helpers, executed by Windows PowerShell: tracked startup cleanup,
environment sanitizing and the isolated Playwright browser store."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from helpers import APP_ROOT, SCRIPTS

MARKER = "photobooth-tracked-startup-test"


def _ps(command: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    common = str(SCRIPTS / "lib" / "common.ps1").replace("'", "''")
    script = f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; . '{common}'; {command}"
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def _q(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sleeper_pids() -> list[int]:
    query = (
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*"
        + MARKER
        + "*' -and $_.Name -eq 'python.exe' } | ForEach-Object { $_.ProcessId }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", query],
        capture_output=True,
        text=True,
        check=False,
    )
    return [int(line) for line in result.stdout.split() if line.strip().isdigit()]


def _wait_no_sleepers(timeout: float = 30) -> list[int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = _sleeper_pids()
        if not pids:
            return []
        time.sleep(0.5)
    return _sleeper_pids()


@pytest.fixture
def record_dir() -> Iterator[Path]:
    folder = Path(tempfile.mkdtemp(prefix="pb-tracked-"))
    try:
        yield folder
    finally:
        for pid in _sleeper_pids():
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        for item in folder.glob("*"):
            item.unlink()
        folder.rmdir()


def _start_line(role: str) -> str:
    # Start-Process joins arguments verbatim, so arguments with spaces carry their own quotes
    # (exactly as run-dummy.ps1 quotes its paths).
    args = f"@('-c', '\"import time; time.sleep(120)\"', '{MARKER}')"
    return (
        f"$null = & $start '{role}' '{MARKER}' {_q(sys.executable)} {args} {_q(APP_ROOT)} '' ''; "
    )


def test_failure_after_starting_children_stops_them_and_clears_record(record_dir: Path) -> None:
    record = record_dir / "processes.json"
    body = "{ param($start) " + _start_line("backend") + _start_line("vite") + "throw 'boom' }"
    result = _ps(f"Invoke-TrackedStartup -RecordPath {_q(record)} -Body {body}")
    assert result.returncode != 0
    assert "boom" in result.stdout + result.stderr
    assert _wait_no_sleepers() == []
    assert not record.exists()


def test_failure_launching_second_child_stops_the_first(record_dir: Path) -> None:
    record = record_dir / "processes.json"
    missing = record_dir / "does-not-exist.exe"
    body = (
        "{ param($start) "
        + _start_line("backend")
        + f"$null = & $start 'vite' 'vite' {_q(missing)} @('x') {_q(APP_ROOT)} '' '' }}"
    )
    result = _ps(f"Invoke-TrackedStartup -RecordPath {_q(record)} -Body {body}")
    assert result.returncode != 0
    assert _wait_no_sleepers() == []
    assert not record.exists()


def test_successful_startup_records_every_child_before_readiness(record_dir: Path) -> None:
    record = record_dir / "processes.json"
    body = "{ param($start) " + _start_line("backend") + _start_line("vite") + "}"
    result = _ps(f"Invoke-TrackedStartup -RecordPath {_q(record)} -Body {body} -Commit abc")
    assert result.returncode == 0, result.stderr
    data = json.loads(record.read_text(encoding="utf-8"))
    assert [p["role"] for p in data["processes"]] == ["backend", "vite"]
    assert all(p["start_time"] != "unknown" for p in data["processes"])

    stop = _ps(
        f"$r = [IO.File]::ReadAllText({_q(record)}) | ConvertFrom-Json; "
        "$left = Stop-RecordedProcesses -Entries @($r.processes); "
        f"Save-ProcessRecord -Path {_q(record)} -Entries $left.ToArray(); exit $left.Count"
    )
    assert stop.returncode == 0, stop.stdout + stop.stderr
    assert _wait_no_sleepers() == []
    assert not record.exists()


def test_clear_environment_removes_inherited_photobooth_and_playwright_variables() -> None:
    env = {
        **os.environ,
        "PHOTOBOOTH_INSTANCE": "main",
        "PHOTOBOOTH_KIOSK_PORT": "8121",
        "PLAYWRIGHT_BROWSERS_PATH": "C:\\shared\\ms-playwright",
    }
    result = _ps(
        "Clear-PhotoboothEnvironment; "
        "@(Get-ChildItem Env: | Where-Object { $_.Name -like 'PHOTOBOOTH_*' -or "
        "$_.Name -eq 'PLAYWRIGHT_BROWSERS_PATH' }).Count",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "0"


def test_playwright_browsers_are_isolated_in_dummy_runtime_storage() -> None:
    result = _ps("$p = Use-IsolatedPlaywrightBrowsers; $env:PLAYWRIGHT_BROWSERS_PATH")
    assert result.returncode == 0, result.stderr
    path = Path(result.stdout.strip().splitlines()[-1])
    assert path == APP_ROOT.parent / "data" / "playwright-browsers"
    assert path.is_dir()
    shared = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    assert path != shared


def test_e2e_script_and_playwright_config_use_the_isolated_store() -> None:
    e2e = (SCRIPTS / "e2e.ps1").read_text(encoding="utf-8")
    config = (APP_ROOT / "e2e" / "playwright.config.ts").read_text(encoding="utf-8")
    assert "Use-IsolatedPlaywrightBrowsers" in e2e
    assert e2e.index("Use-IsolatedPlaywrightBrowsers") < e2e.index("playwright', 'install'")
    assert "PLAYWRIGHT_BROWSERS_PATH" in config
    assert "playwright-browsers" in config
