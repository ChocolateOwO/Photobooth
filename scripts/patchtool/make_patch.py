"""Milestone patch artifacts (stdlib only). Owns creation of `dummy-patch-NNN-slug` tags.

Modes
  --dry-run   refusals + artifacts + restore drill in a temp dir; no tag, nothing published
  (default)   annotated tag, build in patches/.staging-NNN-slug, restore drill, atomic publish
  --resume    tag must already exist at the approved commit; regenerate missing artifacts only
  --repair-index  published folder exists: validate checksums/manifest/tag, append missing index row

Test-only failure injection: env PHOTOBOOTH_MAKE_PATCH_FAIL_AT in {bundle, drill, manifest, index}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

TAG_PREFIX = "dummy-patch-"
BANGKOK = timezone(timedelta(hours=7))
FAIL_ENV = "PHOTOBOOTH_MAKE_PATCH_FAIL_AT"


class PatchError(Exception):
    """A refusal or failure; nothing is published."""


@dataclass(frozen=True)
class Request:
    repo: Path
    patches_dir: Path
    index_file: Path
    number: str
    slug: str
    commit: str
    verify_record: Path | None
    purpose: str
    manual_test: str
    approval: str
    dry_run: bool
    resume: bool
    repair_index: bool = False

    @property
    def name(self) -> str:
        return f"{TAG_PREFIX}{self.number}-{self.slug}"


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8"
    )
    if check and result.returncode != 0:
        raise PatchError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode != 0:
        raise PatchError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


def _inject(step: str) -> None:
    if os.environ.get(FAIL_ENV) == step:
        raise PatchError(f"injected failure at step '{step}'")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tag_numbers(repo: Path) -> dict[int, str]:
    numbers: dict[int, str] = {}
    for tag in git(repo, "tag", "--list", f"{TAG_PREFIX}*").splitlines():
        match = re.fullmatch(rf"{TAG_PREFIX}(\d{{3}})-[a-z0-9-]+", tag.strip())
        if match:
            numbers[int(match.group(1))] = tag.strip()
    return numbers


def _tag_exists(repo: Path, tag: str) -> bool:
    return bool(git(repo, "tag", "--list", tag))


def validate(req: Request) -> tuple[str, str | None]:
    """Run every refusal check. Returns (full commit sha, base tag or None)."""
    if not re.fullmatch(r"\d{3}", req.number) or req.number == "000":
        raise PatchError("number must be three digits, 001 or higher")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", req.slug):
        raise PatchError("slug must be lowercase words joined by '-'")
    commit = git(req.repo, "rev-parse", "--verify", f"{req.commit}^{{commit}}", check=False)
    if not commit:
        raise PatchError(f"approved commit not found: {req.commit}")

    final_dir = req.patches_dir / req.name
    if final_dir.exists():
        raise PatchError(f"patch folder already exists (never overwritten): {final_dir}")

    numbers = _tag_numbers(req.repo)
    number = int(req.number)
    tag_present = _tag_exists(req.repo, req.name)

    if req.resume:
        if not tag_present:
            raise PatchError(f"--resume requires existing tag {req.name}")
        if git(req.repo, "cat-file", "-t", req.name) != "tag":
            raise PatchError(f"{req.name} is not an annotated tag")
        tagged = git(req.repo, "rev-parse", f"{req.name}^{{commit}}")
        if tagged != commit:
            raise PatchError(f"tag {req.name} points to {tagged}, not approved commit {commit}")
        message = git(req.repo, "tag", "-l", "--format=%(contents)", req.name)
        recorded = _tag_evidence(message)
        if recorded.get("approved-commit") != commit:
            raise PatchError("tag message does not record the approved commit")
        record_sha = _check_verify_record(req, commit)
        expected_evidence = {
            "approval": req.approval,
            "manual-test": req.manual_test,
            "verify-record-sha256": record_sha,
        }
        for key, value in expected_evidence.items():
            if recorded.get(key) != value:
                raise PatchError(
                    f"--resume evidence mismatch for '{key}': tag records "
                    f"{recorded.get(key)!r}, got {value!r}"
                )
    else:
        if git(req.repo, "status", "--porcelain", "--untracked-files=all"):
            raise PatchError("working tree is dirty")
        head = git(req.repo, "rev-parse", "HEAD")
        if head != commit:
            raise PatchError(f"HEAD {head} is not the approved commit {commit}")
        if tag_present:
            raise PatchError(f"tag already exists: {req.name}")
        expected = (max(numbers) if numbers else 0) + 1
        if number != expected:
            raise PatchError(f"patch number must be {expected:03d}, got {req.number}")
        if not req.dry_run:
            if req.manual_test not in ("passed", "not_required"):
                raise PatchError(
                    "manual gate must be 'passed' or 'not_required' before publication"
                )
            _check_verify_record(req, commit)

    previous = numbers.get(number - 1)
    if number > 1 and previous is None:
        raise PatchError(f"previous patch tag {number - 1:03d} not found")
    return commit, previous


def _check_verify_record(req: Request, commit: str) -> str:
    """Validate the commit-bound verify record; return its SHA256 (bound into the tag message)."""
    if req.verify_record is None:
        raise PatchError("verify record required (scripts\\verify.ps1 writes one per commit)")
    if not req.verify_record.is_file():
        raise PatchError(f"verify record missing: {req.verify_record}")
    # utf-8-sig: Windows PowerShell 5.1 writers may prepend a BOM.
    record = json.loads(req.verify_record.read_text(encoding="utf-8-sig"))
    if record.get("commit") != commit or record.get("result") != "passed":
        raise PatchError("verify record does not show a passing run for the approved commit")
    return _sha256(req.verify_record)


def _tag_evidence(message: str) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for line in message.splitlines():
        key, sep, value = line.partition(": ")
        if sep and key in ("approved-commit", "approval", "manual-test", "verify-record-sha256"):
            evidence[key] = value.strip()
    return evidence


EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _files_changed(repo: Path, base: str | None, commit: str) -> list[dict[str, object]]:
    """Cumulative changes base..commit (patch 001: from the empty tree)."""
    rng = [base or EMPTY_TREE, commit]
    status = git(repo, "diff", "-M", "--name-status", *rng)
    numstat = git(repo, "diff", "-M", "--numstat", *rng)
    binary = {line.split("\t")[-1] for line in numstat.splitlines() if line.startswith("-\t-\t")}
    files: list[dict[str, object]] = []
    for line in status.splitlines():
        fields = line.split("\t")
        path = fields[-1]
        files.append({"path": path, "status": fields[0][0], "binary": path in binary})
    return files


def _migrations(files: list[dict[str, object]], repo: Path, commit: str) -> dict[str, object]:
    pattern = re.compile(r"backend/alembic/versions/([^/]+)\.py$")
    added = sorted(
        m.group(1) for f in files if f["status"] == "A" and (m := pattern.search(str(f["path"])))
    )
    all_versions = git(
        repo, "ls-tree", "--name-only", f"{commit}:backend/alembic/versions", check=False
    )
    heads = sorted(n[:-3] for n in all_versions.splitlines() if n.endswith(".py"))
    return {"added": added, "head": heads[-1] if heads else None}


def build_artifacts(
    req: Request, commit: str, base_tag: str | None, refname: str, out: Path
) -> dict[str, object]:
    """`refname` is a full ref pinned to `commit`; it is the ONLY ref placed in the bundle."""
    out.mkdir(parents=True)
    if git(req.repo, "rev-parse", f"{refname}^{{commit}}") != commit:
        raise PatchError(f"{refname} does not point to the approved commit")
    base_commit = git(req.repo, "rev-parse", f"{base_tag}^{{commit}}") if base_tag else None

    patch_args = ["format-patch", "--binary", "--stdout"]
    patch_args += ["--root", commit] if base_commit is None else [f"{base_commit}..{commit}"]
    (out / f"{req.name}.patch").write_bytes(git_bytes(req.repo, *patch_args))

    _inject("bundle")
    bundle = out / f"{req.name}.bundle"
    # Never include the moving development branch: later unapproved commits must not leak in.
    git(req.repo, "bundle", "create", str(bundle), refname)
    git(req.repo, "bundle", "verify", str(bundle))
    heads = [
        line.split()[-1] for line in git(req.repo, "bundle", "list-heads", str(bundle)).splitlines()
    ]
    if heads != [refname]:
        raise PatchError(f"bundle must contain only {refname}, found {heads}")

    _inject("drill")
    drill = restore_drill(req.repo, bundle, refname, commit)

    _inject("manifest")
    files = _files_changed(req.repo, base_commit, commit)
    verify = {}
    if req.verify_record and req.verify_record.is_file():
        verify = json.loads(req.verify_record.read_text(encoding="utf-8-sig"))
    manifest: dict[str, object] = {
        "patch_number": req.number,
        "name": req.name,
        "purpose": req.purpose,
        "base_commit": base_commit,
        "resulting_commit": commit,
        "tag": req.name,
        "date": datetime.now(BANGKOK).isoformat(timespec="seconds"),
        "files_changed": files,
        "migrations": _migrations(files, req.repo, commit),
        "tests_run": verify.get("tests", []),
        "manual_test": req.manual_test,
        "user_approval": req.approval,
        "known_limitations": verify.get("known_limitations", []),
        "bundle_verified": True,
        "restore_drill": drill,
        "restore_command": (
            f"git clone {req.name}.bundle restored && "
            f"git -C restored switch -c restore/{req.number} {req.name}"
        ),
        "dry_run": req.dry_run,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "MANIFEST.md").write_text(_manifest_md(manifest), encoding="utf-8")
    sums = [f"{_sha256(p)}  {p.name}" for p in sorted(out.iterdir()) if p.is_file()]
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return manifest


def restore_drill(repo: Path, bundle: Path, refname: str, commit: str) -> dict[str, object]:
    """Restore the bundle into an empty repository outside the project and compare trees."""
    scratch = Path(tempfile.mkdtemp(prefix="pb-restore-drill-"))
    try:
        target = scratch / "restored.git"
        git(scratch, "init", "--quiet", "--bare", str(target))
        git(target, "fetch", "--quiet", str(bundle), "+refs/*:refs/*")
        restored_ref = git(target, "rev-parse", f"{refname}^{{commit}}")
        restored_tree = git(target, "rev-parse", f"{commit}^{{tree}}")
        expected_tree = git(repo, "rev-parse", f"{commit}^{{tree}}")
        extra = git(target, "rev-list", "--all", "--not", commit)
        if restored_tree != expected_tree or restored_ref != commit:
            raise PatchError("restore drill tree mismatch")
        if extra:
            raise PatchError("restore drill found commits beyond the approved commit")
        return {
            "tree_sha_match": True,
            "tree": expected_tree,
            "at": datetime.now(BANGKOK).isoformat(timespec="seconds"),
        }
    finally:
        _force_rmtree(scratch)


def _force_rmtree(path: Path) -> None:
    def onerror(func, p, _exc):  # type: ignore[no-untyped-def]
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if path.exists():
        shutil.rmtree(path, onexc=onerror)


def _manifest_md(m: dict[str, object]) -> str:
    lines = [
        f"# {m['name']}",
        "",
        f"- Purpose: {m['purpose']}",
        f"- Base commit: {m['base_commit'] or '(root)'}",
        f"- Resulting commit: {m['resulting_commit']}",
        f"- Tag: {m['tag']}",
        f"- Date: {m['date']}",
        f"- Manual test: {m['manual_test']}",
        f"- User approval: {m['user_approval']}",
        f"- Bundle verified: {m['bundle_verified']}",
        f"- Restore drill: {m['restore_drill']}",
        f"- Restore: `{m['restore_command']}`",
        "",
        "## Files changed",
        "",
    ]
    for f in m["files_changed"]:  # type: ignore[attr-defined]
        lines.append(f"- {f['status']} {f['path']}{' (binary)' if f['binary'] else ''}")
    lines += ["", "## Migrations", "", f"{m['migrations']}", "", "## Tests", ""]
    for t in m["tests_run"]:  # type: ignore[attr-defined]
        lines.append(f"- {t}")
    return "\n".join(lines) + "\n"


def _make_read_only(folder: Path) -> None:
    for item in folder.iterdir():
        item.chmod(stat.S_IREAD)


def _append_index(index: Path, manifest: dict[str, object]) -> None:
    index.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        index.read_text(encoding="utf-8")
        if index.exists()
        else (
            "# PATCH_INDEX\n\n| Patch | Tag | Commit | Date | Approval |\n|---|---|---|---|---|\n"
        )
    )
    if f"| {manifest['tag']} |" in existing:
        return
    row = (
        f"| {manifest['patch_number']} | {manifest['tag']} | {manifest['resulting_commit']} "
        f"| {manifest['date']} | {manifest['user_approval']} |\n"
    )
    index.write_text(existing + row, encoding="utf-8")


def repair_index(req: Request) -> dict[str, object]:
    """Validate an already-published milestone and append its index row if missing."""
    folder = req.patches_dir / req.name
    if not folder.is_dir():
        raise PatchError(f"--repair-index requires published folder {folder}")
    commit = git(req.repo, "rev-parse", "--verify", f"{req.commit}^{{commit}}", check=False)
    if not commit:
        raise PatchError(f"approved commit not found: {req.commit}")
    if not _tag_exists(req.repo, req.name) or git(req.repo, "cat-file", "-t", req.name) != "tag":
        raise PatchError(f"annotated tag {req.name} not found")
    if git(req.repo, "rev-parse", f"{req.name}^{{commit}}") != commit:
        raise PatchError(f"tag {req.name} does not point to approved commit {commit}")
    for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if _sha256(folder / name) != digest:
            raise PatchError(f"checksum mismatch for {name}")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("resulting_commit") != commit or manifest.get("tag") != req.name:
        raise PatchError("published manifest does not match the approved commit/tag")
    git(req.repo, "bundle", "verify", str(folder / f"{req.name}.bundle"))
    _append_index(req.index_file, manifest)
    return manifest


def run(req: Request) -> dict[str, object]:
    if req.repair_index:
        return repair_index(req)
    commit, base_tag = validate(req)

    if req.dry_run:
        # Temporary private ref pinned to the commit (never a tag, never the moving branch).
        dry_ref = f"refs/photobooth-dry-run/{secrets.token_hex(8)}"
        scratch = Path(tempfile.mkdtemp(prefix="pb-make-patch-dry-"))
        git(req.repo, "update-ref", dry_ref, commit)
        try:
            manifest = build_artifacts(req, commit, base_tag, dry_ref, scratch / "artifacts")
        finally:
            git(req.repo, "update-ref", "-d", dry_ref)
            _force_rmtree(scratch)
        return manifest

    if not req.resume:
        record_sha = _check_verify_record(req, commit)
        message = (
            f"{req.name}\n\napproved-commit: {commit}\napproval: {req.approval}\n"
            f"manual-test: {req.manual_test}\nverify-record-sha256: {record_sha}\n"
        )
        git(req.repo, "tag", "-a", req.name, commit, "-m", message)

    staging = req.patches_dir / f".staging-{req.number}-{req.slug}"
    _force_rmtree(staging)
    try:
        manifest = build_artifacts(req, commit, base_tag, f"refs/tags/{req.name}", staging)
        _make_read_only(staging)
        os.replace(staging, req.patches_dir / req.name)
    except BaseException:
        _force_rmtree(staging)
        raise
    _inject("index")
    _append_index(req.index_file, manifest)
    return manifest


def parse(argv: list[str] | None) -> Request:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--patches-dir", required=True)
    p.add_argument("--index-file", required=True)
    p.add_argument("--number", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--verify-record")
    p.add_argument("--purpose", default="")
    p.add_argument(
        "--manual-test", default="pending", choices=["passed", "not_required", "pending"]
    )
    p.add_argument("--approval", default="pending")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--repair-index", action="store_true")
    a = p.parse_args(argv)
    if not a.dry_run and not a.approval.startswith("approved "):
        p.error("--approval 'approved YYYY-MM-DD' is required unless --dry-run")
    return Request(
        repo=Path(a.repo),
        patches_dir=Path(a.patches_dir),
        index_file=Path(a.index_file),
        number=a.number,
        slug=a.slug,
        commit=a.commit,
        verify_record=Path(a.verify_record) if a.verify_record else None,
        purpose=a.purpose,
        manual_test=a.manual_test,
        approval=a.approval,
        dry_run=a.dry_run,
        resume=a.resume,
        repair_index=a.repair_index,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        manifest = run(parse(argv))
    except PatchError as exc:
        print(f"make-patch REFUSED: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "name": manifest["name"],
                "commit": manifest["resulting_commit"],
                "dry_run": manifest["dry_run"],
                "restore_drill": manifest["restore_drill"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
