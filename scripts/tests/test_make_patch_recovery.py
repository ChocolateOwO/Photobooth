"""make-patch: BOM verify records, failure after publication, index repair."""

from __future__ import annotations

import subprocess
from pathlib import Path

from test_make_patch import NAME, _approved, _baseline, _record, _run, workspace

__all__ = ["workspace"]  # re-exported pytest fixture


def test_verify_record_with_bom_is_accepted(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    record = _record(workspace, commit)
    record.write_bytes(b"\xef\xbb\xbf" + record.read_bytes())
    result = _run(
        workspace, commit, "--verify-record", str(record), "--approval", "approved 2026-09-17"
    )
    assert result.returncode == 0, result.stderr


def test_verify_record_written_by_powershell_is_accepted(workspace: dict[str, Path]) -> None:
    """Same writer expression as scripts/verify.ps1."""
    commit = _baseline(workspace)
    workspace["records"].mkdir(parents=True, exist_ok=True)
    record = workspace["records"] / f"{commit}.json"
    escaped = str(record).replace("'", "''")
    script = (
        f"$json = [ordered]@{{ commit = '{commit}'; result = 'passed'; tests = @() }} "
        "| ConvertTo-Json; "
        f"[System.IO.File]::WriteAllText('{escaped}', $json, "
        "(New-Object System.Text.UTF8Encoding $false))"
    )
    ps = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, check=False
    )
    assert ps.returncode == 0, ps.stderr
    assert record.read_bytes()[:3] != b"\xef\xbb\xbf"
    result = _run(
        workspace, commit, "--verify-record", str(record), "--approval", "approved 2026-09-17"
    )
    assert result.returncode == 0, result.stderr


def test_failure_after_publication_is_repaired_by_repair_index(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    failed = _run(
        workspace,
        commit,
        *_approved(workspace, commit),
        env={"PHOTOBOOTH_MAKE_PATCH_FAIL_AT": "index"},
    )
    assert failed.returncode == 1
    assert (workspace["patches"] / NAME / "manifest.json").is_file()
    assert not workspace["index"].exists()

    blocked = _run(workspace, commit, "--resume", *_approved(workspace, commit))
    assert blocked.returncode == 1

    repaired = _run(workspace, commit, "--repair-index", *_approved(workspace, commit))
    assert repaired.returncode == 0, repaired.stderr
    assert f"| {NAME} |" in workspace["index"].read_text(encoding="utf-8")

    again = _run(workspace, commit, "--repair-index", *_approved(workspace, commit))
    assert again.returncode == 0, again.stderr
    assert workspace["index"].read_text(encoding="utf-8").count(f"| {NAME} |") == 1


def test_repair_index_refuses_tampered_artifacts(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    _run(
        workspace,
        commit,
        *_approved(workspace, commit),
        env={"PHOTOBOOTH_MAKE_PATCH_FAIL_AT": "index"},
    )
    manifest_md = workspace["patches"] / NAME / "MANIFEST.md"
    manifest_md.chmod(0o666)
    manifest_md.write_text("tampered", encoding="utf-8")
    result = _run(workspace, commit, "--repair-index", *_approved(workspace, commit))
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert not workspace["index"].exists()


def test_repair_index_requires_published_folder(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    result = _run(workspace, commit, "--repair-index", *_approved(workspace, commit))
    assert result.returncode == 1
    assert "requires published folder" in result.stderr
