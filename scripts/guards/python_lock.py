"""Resolved Python dependency lock for the backend (runtime + dev + build backend).

    (from backend/, with the venv interpreter)
    python ../scripts/guards/python_lock.py write --pyproject pyproject.toml \
        --lock requirements-dev.lock
    python ../scripts/guards/python_lock.py check --pyproject pyproject.toml \
        --lock requirements-dev.lock

`write` records the exact versions of the installed dependency closure of `photobooth[dev]` plus
the build backend. `check` fails on any drift: missing, extra or different versions installed,
or pyproject requirements the lock no longer satisfies. Run with the backend venv interpreter.

Install a fresh environment from the lock:
    python -m pip install -r requirements-dev.lock
    python -m pip install --no-deps --no-build-isolation -e .
"""

from __future__ import annotations

import argparse
import platform
import sys
import tomllib
from collections.abc import Iterable, Mapping
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PROJECT = "photobooth"
IGNORED = frozenset({"pip", PROJECT})  # installer itself and the editable project


class LockError(Exception):
    """The lock is malformed or the environment/pyproject drifted from it."""


def _installed() -> dict[str, metadata.Distribution]:
    return {canonicalize_name(d.metadata["Name"]): d for d in metadata.distributions()}


def _requirements_of(dist: metadata.Distribution, extras: frozenset[str]) -> list[Requirement]:
    found: list[Requirement] = []
    for raw in dist.requires or []:
        req = Requirement(raw)
        if req.marker is None:
            found.append(req)
            continue
        environments = [{"extra": extra} for extra in extras] or [{"extra": ""}]
        if any(req.marker.evaluate(env) for env in environments):
            found.append(req)
    return found


def resolve_closure(
    pyproject: Mapping[str, object], installed: Mapping[str, metadata.Distribution]
) -> dict[str, str]:
    """Installed versions of everything `photobooth[dev]` and the build backend need."""
    project = installed.get(PROJECT)
    if project is None:
        raise LockError("photobooth is not installed in this interpreter (pip install -e .)")
    build = pyproject.get("build-system", {})
    roots = [Requirement(r) for r in build.get("requires", [])]  # type: ignore[union-attr]
    roots += _requirements_of(project, frozenset({"dev"}))
    closure: dict[str, str] = {}
    pending: list[tuple[Requirement, frozenset[str]]] = [(r, frozenset(r.extras)) for r in roots]
    while pending:
        req, extras = pending.pop()
        name = canonicalize_name(req.name)
        if name in IGNORED:
            continue
        dist = installed.get(name)
        if dist is None:
            raise LockError(f"required package not installed: {req}")
        if not req.specifier.contains(dist.version, prereleases=True):
            raise LockError(f"installed {name}=={dist.version} does not satisfy {req}")
        if name in closure:
            continue
        closure[name] = dist.version
        pending.extend((child, frozenset(child.extras)) for child in _requirements_of(dist, extras))
    return closure


def render_lock(closure: Mapping[str, str]) -> str:
    header = [
        "# Resolved backend dependency lock (runtime + dev + build backend). Do not edit by hand.",
        "# Regenerate: python ../scripts/guards/python_lock.py write "
        "--pyproject pyproject.toml --lock requirements-dev.lock",
        f"# Python {platform.python_version()} on {sys.platform}",
    ]
    return "\n".join(header + [f"{name}=={closure[name]}" for name in sorted(closure)]) + "\n"


def parse_lock(text: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, version = line.partition("==")
        if not sep or not name or not version or " " in line:
            raise LockError(f"lock line {number} is not an exact pin: {raw!r}")
        pins[canonicalize_name(name)] = version
    return pins


def compare(
    lock: Mapping[str, str], closure: Mapping[str, str], extraneous: Iterable[str]
) -> list[str]:
    problems = [f"missing from environment: {n}=={v}" for n, v in lock.items() if n not in closure]
    problems += [f"not in lock: {n}=={v}" for n, v in closure.items() if n not in lock]
    problems += [
        f"version drift: {n} locked {lock[n]}, installed {closure[n]}"
        for n in lock
        if n in closure and lock[n] != closure[n]
    ]
    problems += [f"extraneous installed package: {n}" for n in extraneous]
    return sorted(problems)


def unsatisfied_pyproject(pyproject: Mapping[str, object], lock: Mapping[str, str]) -> list[str]:
    project = pyproject.get("project", {})
    raw = list(project.get("dependencies", []))  # type: ignore[union-attr]
    for extra in project.get("optional-dependencies", {}).values():  # type: ignore[union-attr]
        raw.extend(extra)
    raw.extend(pyproject.get("build-system", {}).get("requires", []))  # type: ignore[union-attr]
    problems: list[str] = []
    for item in raw:
        req = Requirement(item)
        version = lock.get(canonicalize_name(req.name))
        if version is None:
            problems.append(f"pyproject requirement not locked: {req}")
        elif not req.specifier.contains(version, prereleases=True):
            problems.append(f"lock {req.name}=={version} does not satisfy pyproject {req}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("mode", choices=["write", "check"])
    parser.add_argument("--pyproject", required=True)
    parser.add_argument("--lock", required=True)
    args = parser.parse_args(argv)

    pyproject = tomllib.loads(Path(args.pyproject).read_text(encoding="utf-8"))
    installed = _installed()
    try:
        closure = resolve_closure(pyproject, installed)
        if args.mode == "write":
            Path(args.lock).write_text(render_lock(closure), encoding="utf-8", newline="\n")
            print(f"python-lock: wrote {len(closure)} pins")
            return 0
        lock = parse_lock(Path(args.lock).read_text(encoding="utf-8"))
        extraneous = sorted(set(installed) - set(closure) - IGNORED)
        problems = compare(lock, closure, extraneous) + unsatisfied_pyproject(pyproject, lock)
    except LockError as exc:
        print(f"python-lock: {exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"python-lock DRIFT: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"python-lock: ok ({len(lock)} pins match the environment)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
