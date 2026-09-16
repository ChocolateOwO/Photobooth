"""Architecture rules: import-linter contracts plus an independent import-cycle check."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import photobooth

PACKAGE_ROOT = Path(photobooth.__file__).resolve().parent
BACKEND_ROOT = PACKAGE_ROOT.parents[1]


def _module_name(path: Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _internal_imports(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("photobooth"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            base = node.module
            if node.level:
                pkg = module.split(".")[: -node.level]
                base = ".".join([*pkg, node.module])
            if base.startswith("photobooth"):
                found.add(base)
    return found


def _graph() -> dict[str, set[str]]:
    modules = {_module_name(p): p for p in PACKAGE_ROOT.rglob("*.py")}
    graph: dict[str, set[str]] = {}
    for name, path in modules.items():
        targets = set()
        for imported in _internal_imports(path, name):
            # Resolve "photobooth.x.y" (possibly a symbol import) to the closest known module.
            candidate = imported
            while candidate and candidate not in modules:
                candidate = candidate.rpartition(".")[0]
            if candidate and candidate != name and candidate != "photobooth":
                targets.add(candidate)
        graph[name] = targets
    return graph


def test_import_linter_contracts_hold() -> None:
    exe = Path(sys.executable).with_name(
        "lint-imports.exe" if sys.platform == "win32" else "lint-imports"
    )
    result = subprocess.run(
        [str(exe)], cwd=BACKEND_ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 broken" in result.stdout


def test_no_import_cycles() -> None:
    graph = _graph()
    assert "photobooth.core.config" in graph
    visiting: set[str] = set()
    done: set[str] = set()
    cycles: list[list[str]] = []

    def visit(node: str, trail: list[str]) -> None:
        if node in done:
            return
        if node in visiting:
            cycles.append([*trail[trail.index(node) :], node])
            return
        visiting.add(node)
        for nxt in sorted(graph.get(node, ())):
            visit(nxt, [*trail, node])
        visiting.discard(node)
        done.add(node)

    for start in sorted(graph):
        visit(start, [])
    assert not cycles, cycles


def test_domain_modules_have_no_framework_imports() -> None:
    forbidden = ("fastapi", "starlette", "sqlalchemy", "uvicorn", "pydantic")
    for domain in PACKAGE_ROOT.glob("modules/*/domain.py"):
        tree = ast.parse(domain.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(forbidden), f"{domain}: imports {name}"
