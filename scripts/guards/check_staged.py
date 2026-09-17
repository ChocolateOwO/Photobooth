"""Staged-content guard (stdlib only), independent of .gitignore.

Path rules always apply. Value rules detect populated credentials, not identifier names, so this
file, its patterns and its tests can be committed while real secrets are rejected.

Usage:
    python check_staged.py --repo <path> --staged       # pre-commit: index contents
    python check_staged.py --repo <path> --tracked      # verify: all tracked files at HEAD/index
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_BYTES = 5 * 1024 * 1024
BINARY_ALLOWED_PREFIXES = ("backend/tests/fixtures/", "e2e/fixtures/", "frontend/public/")

# ---- path rules -------------------------------------------------------------------------------
SENSITIVE_NAME_PATTERNS = (
    ".env",
    ".env.*",
    "*.env",
    "credentials*.json",
    "token*.json",
    "client_secret*.json",
    "*.pem",
    "*.key",
    "*.sqlite",
    "*.sqlite3",
    "*.sqlite-wal",
    "*.sqlite-shm",
    "*.db",
    "*.db-wal",
    "*.db-shm",
    "*.zip",
    "*.log",
    "pairing.code",
)
NAME_EXCEPTIONS = (".env.example",)
SENSITIVE_DIR_SEGMENTS = (
    "node_modules",
    ".venv",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    "playwright-report",
    "test-results",
    "blob-report",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
)
SENSITIVE_ROOT_DIRS = ("data", "config", "backups", "logs", "storage", "tmp")

# ---- value rules ------------------------------------------------------------------------------
PEM_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=\r\n]{40,}")
GOOGLE_REFRESH_TOKEN = re.compile(r"(?<![A-Za-z0-9])1//[0-9A-Za-z_\-]{30,}")
GOOGLE_ACCESS_TOKEN = re.compile(r"(?<![A-Za-z0-9])ya29\.[0-9A-Za-z_\-]{20,}")
# A pattern of variable names, not a secret.
SECRET_NAME = (
    r"(?P<name>PHOTOBOOTH_ADMIN_PASSWORD|[A-Z0-9_]*_SECRET|[A-Z0-9_]*_TOKEN|[A-Z0-9_]*_PASSWORD)"  # noqa: S105
)
# Source code: only literal-looking values, so `X_TOKEN = re.compile(...)` is not a value.
SOURCE_SECRET_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?"
    + SECRET_NAME
    + r"[ \t]*=[ \t]*(?P<value>\"[^\"\n]*\"|'[^'\n]*'|[^\s#()\[\]{},]*)[ \t\r]*(?:#[^\n]*)?$",
    re.MULTILINE,
)
# Everything else (.env, .env.example, config, text): dotenv syntax, parsed by parse_dotenv_value.
DOTENV_SECRET_NAME = re.compile(r"^[ \t]*(?:export[ \t]+)?" + SECRET_NAME + r"[ \t]*=[ \t]*", re.M)
SOURCE_SUFFIXES = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".ps1", ".psm1", ".sh", ".mako"}
)
JSON_CLIENT_SECRET = re.compile(r'"client_secret"\s*:\s*"(?P<value>[^"]*)"')
JSON_CLIENT_ID = re.compile(r'"client_id"\s*:\s*"(?P<value>[^"]*)"')
SYNTHETIC_MARKER = "SYNTHETIC-TEST-VALUE"
PLACEHOLDER = re.compile(r"^(|changeme|<[^>]*>|\$\{[^}]*\}|SYNTHETIC-TEST-VALUE)$", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    path: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.rule}] {self.detail}"


def path_violations(path: str) -> list[Violation]:
    posix = path.replace("\\", "/")
    parts = posix.split("/")
    name = parts[-1]
    found: list[Violation] = []
    if name not in NAME_EXCEPTIONS and any(
        fnmatch.fnmatch(name, p) for p in SENSITIVE_NAME_PATTERNS
    ):
        found.append(Violation(posix, "sensitive-path", f"file name '{name}' is never committed"))
    if any(seg in SENSITIVE_DIR_SEGMENTS for seg in parts[:-1]):
        found.append(Violation(posix, "sensitive-path", "generated/tooling directory"))
    if len(parts) > 1 and parts[0] in SENSITIVE_ROOT_DIRS:
        found.append(Violation(posix, "sensitive-path", f"runtime directory '{parts[0]}/'"))
    return found


def _is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER.match(value.strip().strip("\"'")))


def parse_dotenv_value(text: str, start: int) -> str:
    """Value at `start` using dotenv rules: quoted values may contain anything (including newlines
    and `#`); unquoted values run to end of line, minus an inline ` #comment`."""
    if start < len(text) and text[start] in "\"'":
        quote = text[start]
        index = start + 1
        chars: list[str] = []
        while index < len(text):
            char = text[index]
            if char == "\\" and quote == '"' and index + 1 < len(text):
                chars.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                return "".join(chars)
            chars.append(char)
            index += 1
        return "".join(chars)  # unterminated: treat the remainder as the value
    end = text.find("\n", start)
    line = text[start:] if end == -1 else text[start:end]
    comment = re.search(r"[ \t]#", line)
    if comment:
        line = line[: comment.start()]
    elif line.startswith("#"):
        line = ""
    return line.strip()


def _secret_assignments(path: str, text: str) -> list[tuple[str, str]]:
    if PurePosixPath(path).suffix.lower() in SOURCE_SUFFIXES:
        return [
            (m.group("name"), m.group("value")) for m in SOURCE_SECRET_ASSIGNMENT.finditer(text)
        ]
    return [
        (m.group("name"), parse_dotenv_value(text, m.end()))
        for m in DOTENV_SECRET_NAME.finditer(text)
    ]


def value_violations(path: str, data: bytes) -> list[Violation]:
    posix = path.replace("\\", "/")
    text = data.decode("utf-8", errors="ignore")
    found: list[Violation] = []
    if PEM_PRIVATE_KEY.search(text):
        found.append(Violation(posix, "private-key", "PEM private key body"))
    if GOOGLE_REFRESH_TOKEN.search(text):
        found.append(Violation(posix, "refresh-token", "OAuth refresh token value"))
    if GOOGLE_ACCESS_TOKEN.search(text):
        found.append(Violation(posix, "access-token", "OAuth access token value"))
    for name, value in _secret_assignments(posix, text):
        if not _is_placeholder(value):
            found.append(Violation(posix, "secret-assignment", f"{name} has a value"))
    secrets_ = [m.group("value") for m in JSON_CLIENT_SECRET.finditer(text)]
    ids = [m.group("value") for m in JSON_CLIENT_ID.finditer(text)]
    if any(not _is_placeholder(s) for s in secrets_) and any(not _is_placeholder(i) for i in ids):
        found.append(Violation(posix, "client-secret", "populated OAuth client credentials"))
    return found


def content_violations(path: str, data: bytes) -> list[Violation]:
    posix = path.replace("\\", "/")
    found: list[Violation] = []
    if len(data) > MAX_BYTES:
        found.append(Violation(posix, "size", f"{len(data)} bytes > {MAX_BYTES}"))
    if b"\0" in data[:8000] and not posix.startswith(BINARY_ALLOWED_PREFIXES):
        found.append(Violation(posix, "binary", "binary file outside allowed fixture/public dirs"))
    found.extend(value_violations(posix, data))
    return found


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def _entries(repo: Path, staged: bool) -> Iterator[tuple[str, bytes]]:
    if staged:
        raw = _git(repo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    else:
        raw = _git(repo, "ls-files", "-z", "--cached")
    for name in (n for n in raw.decode("utf-8").split("\0") if n):
        yield name, _git(repo, "show", f":{name}")


def check(entries: Iterable[tuple[str, bytes]]) -> list[Violation]:
    violations: list[Violation] = []
    for path, data in entries:
        violations.extend(path_violations(path))
        violations.extend(content_violations(path, data))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--tracked", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    violations = check(_entries(Path(args.repo), staged=args.staged))
    if args.json:
        print(json.dumps([v.__dict__ for v in violations], indent=2))
    for violation in violations:
        print(f"BLOCKED {violation}", file=sys.stderr)
    if not violations:
        print("check-staged: ok")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
