"""Main scripts: the first-install refusals that happen before anything is written, the Main
launcher's layout check, and stop-main.ps1 stopping only a matching recorded process.

Nothing here creates or touches the real Main folder: every refusal is reached before any write,
and the folders used live under the system temp dir.
"""

from __future__ import annotations

import _winapi
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
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


# ---- the independent review's findings (P13-R1 .. R7) ----------------------------------------


def _run_env(script: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPTS / script), *args,
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=env,
    )  # fmt: skip


def test_a_rehearsal_never_goes_inside_the_project_whatever_temp_says() -> None:
    """P13-R1. A commit that does not exist backs the guard up: even if the path check failed,
    nothing could be cloned or written."""
    inside = APP_ROOT.parent  # <project>\Dummy, an existing folder inside the project
    env = os.environ | {"TEMP": str(inside), "TMP": str(inside)}
    target = inside / "Main"
    result = _run_env(
        "install-main.ps1", env, "-Commit", "0" * 40, "-Rehearsal", "-MainRoot", str(target)
    )
    assert result.returncode != 0
    assert "never goes inside the project" in result.stdout + result.stderr
    assert not target.exists()


def test_a_junction_on_the_way_is_refused(temp_base: Path) -> None:
    """P13-R2: a junction can make a folder that reads like temp lead somewhere else."""
    elsewhere = temp_base / "elsewhere"
    elsewhere.mkdir()
    alias = temp_base / "alias"
    _winapi.CreateJunction(str(elsewhere), str(alias))
    try:
        result = _run(
            "install-main.ps1", "-Commit", "0" * 40, "-Rehearsal", "-MainRoot", str(alias / "Main")
        )
        assert result.returncode != 0
        assert "is a junction or link" in result.stdout + result.stderr
        assert list(elsewhere.iterdir()) == []
    finally:
        os.rmdir(alias)  # the junction only, never its target


def test_a_short_path_name_is_refused(temp_base: Path) -> None:
    result = _run(
        "install-main.ps1",
        "-Commit",
        "0" * 40,
        "-Rehearsal",
        "-MainRoot",
        str(temp_base / "MAIN~1" / "Main"),
    )
    assert result.returncode != 0
    assert "short (8.3) path" in result.stdout + result.stderr


def test_stop_main_refuses_a_record_that_is_not_mains(temp_base: Path) -> None:
    """P13-R7: a Dummy record (or any other) is never acted on by the Main stopper."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", MARKER])
    pid_file = temp_base / "dummy-processes.json"
    try:
        ident = _identity(proc)
        record = {
            "instance": "dummy",
            "processes": [{"role": "backend", "pid": proc.pid, "marker": MARKER, **ident}],
        }
        pid_file.write_text(json.dumps(record), encoding="utf-8")
        result = _run("stop-main.ps1", "-PidFile", str(pid_file))
        assert result.returncode == 2
        assert proc.poll() is None, "a process of another instance must survive"
        assert json.loads(pid_file.read_text(encoding="utf-8")) == record  # untouched
    finally:
        _kill_tree(proc)


def test_stop_main_takes_no_record_from_inside_the_project() -> None:
    dummy_record = APP_ROOT.parent / "data" / "run" / "dummy-processes.json"
    before = dummy_record.read_bytes() if dummy_record.exists() else None
    result = _run("stop-main.ps1", "-PidFile", str(dummy_record))
    assert result.returncode != 0
    assert "isolated tests only" in result.stdout + result.stderr
    after = dummy_record.read_bytes() if dummy_record.exists() else None
    assert after == before


def test_a_refused_main_start_writes_nothing(temp_base: Path) -> None:
    """P13-R6: run-main.ps1 checks everything before its first write."""
    main = temp_base / "Main"
    scripts = main / "app" / "scripts"
    shutil.copytree(SCRIPTS / "lib", scripts / "lib")
    shutil.copy2(SCRIPTS / "run-main.ps1", scripts / "run-main.ps1")
    result = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(scripts / "run-main.ps1"), "-NoBrowser",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )  # fmt: skip
    assert result.returncode != 0
    assert "No Main settings" in result.stdout + result.stderr
    assert sorted(p.name for p in main.iterdir()) == ["app"]  # no data, no config, no logs


def test_stopping_a_recorded_process_leaves_nothing_it_started_running(temp_base: Path) -> None:
    """The race fix, completed: after a stop, no process of the recorded tree runs on (a venv
    launcher, its interpreter and what that started), and the record is cleared."""
    record = temp_base / "processes.json"
    probe = "pb-child-probe-" + secrets.token_hex(4)
    script = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)', "
        f"'{MARKER}', '{probe}']); "
        "time.sleep(120)"
    )
    parent = subprocess.Popen([sys.executable, "-c", script, MARKER])
    try:
        ident = _identity(parent)
        deadline = time.monotonic() + 30
        while not _probes(probe) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert _probes(probe), "the child under test started"
        record.write_text(
            json.dumps(
                {
                    "instance": "main",
                    "processes": [
                        {"role": "backend", "pid": parent.pid, "marker": MARKER, **ident}
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = _run("stop-main.ps1", "-PidFile", str(record))
        assert result.returncode == 0, result.stdout + result.stderr
        assert not record.exists()
        time.sleep(1)
        assert _probes(probe) == []
    finally:
        for pid in _probes(probe):
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False
            )
        if parent.poll() is None:
            _kill_tree(parent)


def _probes(probe: str) -> list[int]:
    query = (
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*"
        + probe
        + "*' -and $_.Name -eq 'python.exe' } | ForEach-Object { $_.ProcessId }"
    )
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", query],
        capture_output=True, text=True, check=False,
    ).stdout  # fmt: skip
    return [int(x) for x in out.split() if x.strip().isdigit()]


# ---- installing a published release from a fresh clone (README) ---------------------------------
# Every -Release test runs the installer from a throwaway clone laid out as <temp>\proj\Dummy\app,
# so its "real Main" is <temp>\proj\Main: whatever the owner's machine holds, nothing outside the
# temp folder is ever a target (P13 review R4). Only refusals are exercised here.


def _fresh_clone(base: Path) -> tuple[Path, str]:
    app = base / "proj" / "Dummy" / "app"
    shutil.copytree(SCRIPTS, app / "scripts", ignore=shutil.ignore_patterns("__pycache__", "tests"))
    git(app, "init", "-q", "-b", "main")
    for key, value in (
        ("user.name", "photobooth-test"),
        ("user.email", "test@example.invalid"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
    ):
        git(app, "config", key, value)
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", "release")
    return app, git(app, "rev-parse", "HEAD")


def _run_in(app: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(app / "scripts" / "install-main.ps1"), *args,
        ],
        input=b"", capture_output=True, check=False,
    )  # fmt: skip


def _said(result: subprocess.CompletedProcess[bytes]) -> str:
    return (result.stdout + result.stderr).decode("utf-8", "replace")


def test_a_release_must_be_an_annotated_milestone_tag_with_its_evidence(temp_base: Path) -> None:
    app, head = _fresh_clone(temp_base)
    git(app, "tag", "dummy-patch-001-light")
    git(app, "tag", "-a", "dummy-patch-002-bare", "-m", "no evidence")
    git(app, "tag", "-a", "dummy-patch-003-other", "-m",
        f"approved-commit: {'0' * 40}\napproval: approved 2026-10-04\nmanual-test: passed\n"
        f"verify-record-sha256: {'a' * 64}")  # fmt: skip
    git(app, "tag", "-a", "dummy-patch-004-pending", "-m",
        f"approved-commit: {head}\napproval: pending\nmanual-test: passed\n"
        f"verify-record-sha256: {'a' * 64}")  # fmt: skip
    for tag, refusal in (
        ("dummy-patch-999-not-published", "is not in this clone"),
        ("dummy-patch-001-light", "is not an annotated tag"),
        ("dummy-patch-002-bare", "does not record"),
        ("dummy-patch-003-other", "does not record"),
        ("dummy-patch-004-pending", "records no approval"),
        ("v1.0", "Not a milestone tag"),
    ):
        result = _run_in(app, "-Release", tag)
        assert result.returncode != 0, tag
        assert refusal in _said(result), (tag, _said(result))
    assert not (temp_base / "proj" / "Main").exists()


def test_a_release_is_never_mixed_with_a_rehearsal_or_another_tag(temp_base: Path) -> None:
    app, _ = _fresh_clone(temp_base)
    for extra in (
        ["-Rehearsal", "-MainRoot", str(temp_base / "Main")],
        ["-Tag", "dummy-patch-006-x"],
    ):
        result = _run_in(app, "-Release", "dummy-patch-006-booth-camera-capture", *extra)
        assert result.returncode != 0
        assert "not with -Rehearsal or -Tag" in _said(result)
    assert not (temp_base / "Main").exists()
    assert not (temp_base / "proj" / "Main").exists()


def test_the_installer_needs_a_source(temp_base: Path) -> None:
    app, _ = _fresh_clone(temp_base)
    result = _run_in(app)
    assert result.returncode != 0
    assert "Name the source" in _said(result)


def test_a_piped_password_must_be_there(temp_base: Path) -> None:
    app, _ = _fresh_clone(temp_base)
    result = _run_in(app, "-Release", "dummy-patch-999-not-published", "-AdminPasswordStdin")
    assert result.returncode != 0
    assert "no password on the first line" in _said(result)
    assert not (temp_base / "proj" / "Main").exists()


def test_a_piped_password_reaches_python_as_the_same_utf8_text(temp_base: Path) -> None:
    # Read-StdinLineUtf8 + Invoke-NativeWithLine (P13 review R3): characters outside the console
    # code page survive the PowerShell pipe into a Python child unchanged, and nothing is left set.
    password = "รหัสผ่านแอดมิน-ü-€-a long enough admin password"
    # The child reads like photobooth's --password-stdin: PowerShell 5.1 adds a BOM, which it drops.
    child = temp_base / "child.py"
    child.write_text(
        "import sys\n"
        "line = sys.stdin.readline().rstrip('\\r\\n').removeprefix('\\ufeff')\n"
        "print(ascii(line))\n",
        encoding="utf-8",
    )
    probe = temp_base / "probe.ps1"
    probe.write_text(
        "\ufeff. '" + str(SCRIPTS / "lib" / "common.ps1") + "'\n"
        "$line = Read-StdinLineUtf8\n"
        "$before = [string]$OutputEncoding.WebName\n"
        "Invoke-NativeWithLine -FilePath '" + sys.executable + "' "
        "-Arguments @('" + str(child) + "') -Line $line\n"
        "$same = [string]$OutputEncoding.WebName -eq $before\n"
        "Write-Output ('after ' + $same + ' ' + ($null -eq $env:PYTHONIOENCODING))\n",
        encoding="utf-8",
    )  # fmt: skip
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
        input=b"\xef\xbb\xbf" + password.encode("utf-8") + b"\r\n", capture_output=True, env=env,
        check=False,
    )  # fmt: skip
    out = result.stdout.decode("utf-8", "replace")
    assert result.returncode == 0, _said(result)
    assert ascii(password) in out
    assert "after True True" in out
