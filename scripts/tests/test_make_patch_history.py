"""make-patch: linear milestone history, independent patch drill, Alembic metadata."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from test_make_patch import NAME, _approved, _baseline, _run, workspace

from helpers import SCRIPTS, commit_file, git

__all__ = ["workspace"]  # re-exported pytest fixture


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "make_patch_under_test", SCRIPTS / "patchtool" / "make_patch.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _migration(revision: str, down: str | None) -> str:
    down_expr = "None" if down is None else f'"{down}"'
    return f'revision: str = "{revision}"\ndown_revision: str | None = {down_expr}\n'


def test_real_run_records_successful_patch_drill(workspace: dict[str, Path]) -> None:
    commit = _baseline(workspace)
    result = _run(workspace, commit, *_approved(workspace, commit))
    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (workspace["patches"] / NAME / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["patch_drill"]["tree_sha_match"] is True
    assert manifest["patch_drill"]["base"] is None


def test_second_milestone_patch_applies_on_previous_milestone(workspace: dict[str, Path]) -> None:
    first = _baseline(workspace)
    assert _run(workspace, first, *_approved(workspace, first)).returncode == 0
    second = commit_file(workspace["repo"], "src/feature.txt", "phase 2\n", "patch-002: feature")
    result = _run(workspace, second, *_approved(workspace, second), number="002", slug="feature")
    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (workspace["patches"] / "dummy-patch-002-feature" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["base_commit"] == first
    assert manifest["patch_drill"] == {**manifest["patch_drill"], "tree_sha_match": True}
    assert manifest["patch_drill"]["base"] == first


def test_merge_commit_in_milestone_range_is_refused(workspace: dict[str, Path]) -> None:
    repo = workspace["repo"]
    _baseline(workspace)
    git(repo, "switch", "-q", "-c", "ui/001-work")
    commit_file(repo, "frontend/a.txt", "ui\n", "ui work")
    git(repo, "switch", "-q", "dummy")
    commit_file(repo, "backend/b.txt", "backend\n", "backend work")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge ui", "ui/001-work")
    merged = git(repo, "rev-parse", "HEAD")

    result = _run(workspace, merged, *_approved(workspace, merged))
    assert result.returncode == 1
    assert "merge commits" in result.stderr
    assert not git(repo, "tag", "--list")
    dry = _run(workspace, merged, "--dry-run")
    assert dry.returncode == 1


def test_previous_milestone_must_be_an_ancestor(workspace: dict[str, Path]) -> None:
    repo = workspace["repo"]
    first = _baseline(workspace)
    assert _run(workspace, first, *_approved(workspace, first)).returncode == 0
    # Build a divergent history that does not contain milestone 001.
    git(repo, "switch", "-q", "--orphan", "rewritten")
    commit_file(repo, "other.txt", "unrelated\n", "unrelated root")
    git(repo, "clean", "-fdq")
    other = git(repo, "rev-parse", "HEAD")

    result = _run(workspace, other, *_approved(workspace, other), number="002", slug="orphan")
    assert result.returncode == 1
    assert "not an ancestor" in result.stderr


def test_patch_drill_detects_tree_mismatch(workspace: dict[str, Path], tmp_path: Path) -> None:
    tool = _tool()
    commit = _baseline(workspace)
    repo = workspace["repo"]
    patch = tmp_path / "p.patch"
    patch.write_bytes(
        tool.git_bytes(repo, "format-patch", "--binary", "--stdout", "--root", commit)
    )
    git(repo, "tag", "-a", "drill-ref", "-m", "x", commit)
    bundle = tmp_path / "b.bundle"
    git(repo, "bundle", "create", str(bundle), "refs/tags/drill-ref")

    good_tree = git(repo, "rev-parse", f"{commit}^{{tree}}")
    assert tool.restore_patch_drill(bundle, patch, None, commit, good_tree)["tree_sha_match"]
    with pytest.raises(tool.PatchError, match="tree mismatch"):
        tool.restore_patch_drill(bundle, patch, None, commit, "0" * 40)


def test_migration_head_comes_from_revision_metadata_not_file_names(
    workspace: dict[str, Path],
) -> None:
    repo = workspace["repo"]
    commit_file(repo, "README.md", "x\n", "root")
    # Lexical file order (aaa < zzz) is the reverse of migration order.
    commit_file(repo, "backend/alembic/versions/zzz_first.py", _migration("b1f00d", None), "m1")
    commit = commit_file(
        repo, "backend/alembic/versions/aaa_add_profiles.py", _migration("a2c0de", "b1f00d"), "m2"
    )
    result = _run(workspace, commit, *_approved(workspace, commit))
    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (workspace["patches"] / NAME / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["migrations"] == {"added": ["a2c0de", "b1f00d"], "head": "a2c0de"}


def test_multiple_alembic_heads_are_refused_before_tagging(workspace: dict[str, Path]) -> None:
    repo = workspace["repo"]
    commit_file(repo, "README.md", "x\n", "root")
    commit_file(repo, "backend/alembic/versions/base.py", _migration("base0", None), "m0")
    commit_file(repo, "backend/alembic/versions/left.py", _migration("left1", "base0"), "m1")
    commit = commit_file(
        repo, "backend/alembic/versions/right.py", _migration("right1", "base0"), "m2"
    )
    result = _run(workspace, commit, *_approved(workspace, commit))
    assert result.returncode == 1
    assert "exactly one Alembic head" in result.stderr
    assert not git(repo, "tag", "--list")


def test_patch_drill_handles_empty_baseline_commit(workspace: dict[str, Path]) -> None:
    """The real repository starts with an empty `patch-000` commit; the drill must replay it."""
    repo = workspace["repo"]
    git(repo, "commit", "-q", "--allow-empty", "-m", "patch-000: empty repository baseline")
    commit = _baseline(workspace)
    result = _run(workspace, commit, *_approved(workspace, commit))
    assert result.returncode == 0, result.stderr
    dry = _run(workspace, commit, "--dry-run")
    assert dry.returncode == 1  # tag now exists; the real run above already proved the drill
