"""make-patch in throwaway repositories outside Photobooth: refusals, dry run, real run, resume."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from helpers import SCRIPTS, commit_file, git, new_repo, remove_tree

TOOL = SCRIPTS / "patchtool" / "make_patch.py"
NAME = "dummy-patch-001-project-foundation"


@pytest.fixture
def workspace() -> Iterator[dict[str, Path]]:
    repo = new_repo("patch")
    outside = repo.parent / f"{repo.name}-out"
    outside.mkdir()
    try:
        yield {
            "repo": repo,
            "patches": outside / "patches",
            "index": outside / "Project_Docs" / "PATCH_INDEX.md",
            "records": outside / "verify",
        }
    finally:
        remove_tree(repo)
        remove_tree(outside)


def _record(ws: dict[str, Path], commit: str, result: str = "passed") -> Path:
    ws["records"].mkdir(parents=True, exist_ok=True)
    path = ws["records"] / f"{commit}.json"
    path.write_text(
        json.dumps({"commit": commit, "result": result, "tests": [{"suite": "pytest"}]}),
        encoding="utf-8",
    )
    return path


def _run(
    ws: dict[str, Path],
    commit: str,
    *extra: str,
    number: str = "001",
    slug: str = "project-foundation",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    import os

    args = [
        sys.executable,
        str(TOOL),
        "--repo",
        str(ws["repo"]),
        "--patches-dir",
        str(ws["patches"]),
        "--index-file",
        str(ws["index"]),
        "--number",
        number,
        "--slug",
        slug,
        "--commit",
        commit,
        *extra,
    ]
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, **(env or {})},
    )


def _approved(ws: dict[str, Path], commit: str) -> list[str]:
    return [
        "--verify-record",
        str(_record(ws, commit)),
        "--approval",
        "approved 2026-09-17",
        "--manual-test",
        "passed",
    ]


def _baseline(ws: dict[str, Path]) -> str:
    commit_file(ws["repo"], "README.md", "ทดสอบ\n", "patch-000: baseline")
    commit_file(ws["repo"], "fixtures/pixel.bin", b"\x00\x01binary", "add binary")
    migration = 'revision: str = "0001_baseline"\ndown_revision: str | None = None\n'
    return commit_file(
        ws["repo"], "backend/alembic/versions/0001_baseline.py", migration, "patch-001"
    )


def test_dry_run_refuses_dirty_tree(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    (workspace["repo"] / "untracked.txt").write_text("dirty", encoding="utf-8")
    result = _run(workspace, commit, "--dry-run")
    assert result.returncode == 1
    assert "dirty" in result.stderr


def test_dry_run_refuses_head_not_approved(workspace: dict[str, Path]) -> None:
    first = _baseline(workspace)
    commit_file(workspace["repo"], "later.txt", "later", "later commit")
    result = _run(workspace, first, "--dry-run")
    assert result.returncode == 1
    assert "is not the approved commit" in result.stderr


def test_dry_run_refuses_existing_tag(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    git(workspace["repo"], "tag", "-a", NAME, "-m", "x")
    result = _run(workspace, commit, "--dry-run")
    assert result.returncode == 1
    assert "tag already exists" in result.stderr


def test_refuses_wrong_sequence_number(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    result = _run(workspace, commit, "--dry-run", number="002")
    assert result.returncode == 1
    assert "must be 001" in result.stderr


def test_real_run_requires_passing_verify_record(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    bad = _record(workspace, commit, result="failed")
    result = _run(
        workspace, commit, "--verify-record", str(bad), "--approval", "approved 2026-09-17",
        "--manual-test", "passed",
    )  # fmt: skip
    assert result.returncode == 1
    assert "verify record" in result.stderr
    assert not git(workspace["repo"], "tag", "--list")


def test_real_run_requires_approval_text(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    result = _run(workspace, commit, "--verify-record", str(_record(workspace, commit)))
    assert result.returncode != 0
    assert not git(workspace["repo"], "tag", "--list")


def test_dry_run_creates_nothing_and_drill_matches(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    result = _run(workspace, commit, "--dry-run")
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["dry_run"] is True
    assert summary["restore_drill"]["tree_sha_match"] is True
    assert not git(workspace["repo"], "tag", "--list")
    assert not workspace["patches"].exists()
    assert not workspace["index"].exists()


def test_real_run_publishes_self_contained_bundle(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    result = _run(workspace, commit, *_approved(workspace, commit))
    assert result.returncode == 0, result.stderr

    folder = workspace["patches"] / NAME
    names = {p.name for p in folder.iterdir()}
    assert names == {
        f"{NAME}.patch",
        f"{NAME}.bundle",
        "manifest.json",
        "MANIFEST.md",
        "SHA256SUMS.txt",
    }
    assert not list(workspace["patches"].glob(".staging-*"))
    assert git(workspace["repo"], "cat-file", "-t", NAME) == "tag"
    assert git(workspace["repo"], "rev-parse", f"{NAME}^{{commit}}") == commit

    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["base_commit"] is None
    assert manifest["resulting_commit"] == commit
    assert manifest["migrations"] == {"added": ["0001_baseline"], "head": "0001_baseline"}
    assert {"path": "fixtures/pixel.bin", "status": "A", "binary": True} in manifest[
        "files_changed"
    ]
    assert manifest["user_approval"] == "approved 2026-09-17"

    # Independent restore from the bundle alone into a brand-new empty directory.
    target = workspace["patches"].parent / "restore-check"
    clone = subprocess.run(
        ["git", "clone", "--quiet", str(folder / f"{NAME}.bundle"), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert clone.returncode == 0, clone.stderr
    assert git(target, "rev-parse", f"{NAME}^{{tree}}") == git(
        workspace["repo"], "rev-parse", f"{commit}^{{tree}}"
    )
    assert (
        len(git(target, "rev-list", NAME).splitlines()) == 3
    )  # complete history, no base exclusion

    index = workspace["index"].read_text(encoding="utf-8")
    assert f"| {NAME} |" in index

    again = _run(workspace, commit, *_approved(workspace, commit))
    assert again.returncode == 1
    assert "already exists" in again.stderr


@pytest.mark.parametrize("step", ["bundle", "drill", "manifest"])
def test_failure_then_resume(workspace: dict[str, Path], step: str) -> None:
    commit = _baseline(workspace)
    failed = _run(
        workspace,
        commit,
        *_approved(workspace, commit),
        env={"PHOTOBOOTH_MAKE_PATCH_FAIL_AT": step},
    )
    assert failed.returncode == 1
    assert f"injected failure at step '{step}'" in failed.stderr
    assert not (workspace["patches"] / NAME).exists()
    assert not list(workspace["patches"].glob(".staging-*"))
    tag_sha = git(workspace["repo"], "rev-parse", NAME)

    resumed = _run(workspace, commit, "--resume", *_approved(workspace, commit))
    assert resumed.returncode == 0, resumed.stderr
    assert (workspace["patches"] / NAME / "manifest.json").is_file()
    assert git(workspace["repo"], "rev-parse", NAME) == tag_sha

    twice = _run(workspace, commit, "--resume", *_approved(workspace, commit))
    assert twice.returncode == 1


def test_resume_refuses_mismatched_commit(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    _run(
        workspace,
        commit,
        *_approved(workspace, commit),
        env={"PHOTOBOOTH_MAKE_PATCH_FAIL_AT": "drill"},
    )
    other = commit_file(workspace["repo"], "other.txt", "x", "other")
    result = _run(workspace, other, "--resume", *_approved(workspace, other))
    assert result.returncode == 1
    assert "not approved commit" in result.stderr


def test_resume_requires_existing_tag(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    result = _run(workspace, commit, "--resume", *_approved(workspace, commit))
    assert result.returncode == 1
    assert "requires existing tag" in result.stderr
