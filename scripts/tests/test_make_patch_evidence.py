"""make-patch evidence binding: pinned bundle refs, manual gate, resume evidence checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from test_make_patch import NAME, _approved, _baseline, _record, _run, workspace

from helpers import commit_file, git

__all__ = ["workspace"]  # re-exported pytest fixture


def test_publication_refuses_pending_manual_gate(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    result = _run(
        workspace,
        commit,
        "--verify-record",
        str(_record(workspace, commit)),
        "--approval",
        "approved 2026-09-17",
        "--manual-test",
        "pending",
    )
    assert result.returncode == 1
    assert "manual gate" in result.stderr
    assert not git(workspace["repo"], "tag", "--list")


def test_resume_after_branch_advanced_bundles_only_the_approved_commit(
    workspace: dict[str, Path],
) -> None:
    commit = _baseline(workspace)
    failed = _run(
        workspace,
        commit,
        *_approved(workspace, commit),
        env={"PHOTOBOOTH_MAKE_PATCH_FAIL_AT": "drill"},
    )
    assert failed.returncode == 1
    later = commit_file(workspace["repo"], "unapproved.txt", "later work", "unapproved later")

    resumed = _run(workspace, commit, "--resume", *_approved(workspace, commit))
    assert resumed.returncode == 0, resumed.stderr

    bundle = workspace["patches"] / NAME / f"{NAME}.bundle"
    heads = git(workspace["repo"], "bundle", "list-heads", str(bundle)).splitlines()
    assert [h.split()[-1] for h in heads] == [f"refs/tags/{NAME}"]

    restored = workspace["patches"].parent / "restored.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(restored)], check=True)
    git(restored, "fetch", "--quiet", str(bundle), "+refs/*:refs/*")
    all_commits = git(restored, "rev-list", "--all").splitlines()
    assert commit in all_commits
    assert later not in all_commits


def test_dry_run_bundle_excludes_branch_and_leaves_no_refs(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    refs_before = git(workspace["repo"], "for-each-ref", "--format=%(refname)")
    result = _run(workspace, commit, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert git(workspace["repo"], "for-each-ref", "--format=%(refname)") == refs_before


def test_resume_requires_verify_record(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    _run(
        workspace,
        commit,
        *_approved(workspace, commit),
        env={"PHOTOBOOTH_MAKE_PATCH_FAIL_AT": "manifest"},
    )
    (workspace["records"] / f"{commit}.json").unlink()
    result = _run(
        workspace,
        commit,
        "--resume",
        "--verify-record",
        str(workspace["records"] / f"{commit}.json"),
        "--approval",
        "approved 2026-09-17",
        "--manual-test",
        "passed",
    )
    assert result.returncode == 1
    assert "verify record missing" in result.stderr


def test_resume_refuses_changed_record_or_different_approval(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    _run(
        workspace,
        commit,
        *_approved(workspace, commit),
        env={"PHOTOBOOTH_MAKE_PATCH_FAIL_AT": "manifest"},
    )
    record = workspace["records"] / f"{commit}.json"

    different_approval = _run(
        workspace,
        commit,
        "--resume",
        "--verify-record",
        str(_record(workspace, commit)),
        "--approval",
        "approved 2099-01-01",
        "--manual-test",
        "passed",
    )
    assert different_approval.returncode == 1
    assert "evidence mismatch for 'approval'" in different_approval.stderr

    record.write_text(record.read_text(encoding="utf-8") + " ", encoding="utf-8")
    changed_record = _run(
        workspace,
        commit,
        "--resume",
        "--verify-record",
        str(record),
        "--approval",
        "approved 2026-09-17",
        "--manual-test",
        "passed",
    )
    assert changed_record.returncode == 1
    assert "verify-record-sha256" in changed_record.stderr
