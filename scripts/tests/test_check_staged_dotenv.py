"""dotenv assignment syntax variants. Secret-like lines are assembled at runtime from fragments."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_check_staged import _run, _stage, repo

__all__ = ["repo"]  # re-exported pytest fixture

PASSWORD = "PHOTOBOOTH_ADMIN_" + "PASSWORD"
SECRET = "DRIVE_CLIENT_" + "SECRET"
TOKEN = "DRIVE_REFRESH_" + "TOKEN"


@pytest.mark.parametrize(
    "line",
    [
        PASSWORD + "= hunter2hunter2",
        PASSWORD + " = hunter2hunter2",
        PASSWORD + '= "  hunter2hunter2"',
        "export " + SECRET + "='abc123def456'",
        TOKEN + "=abc123def456  # real value",
        "  " + PASSWORD + "=hunter2hunter2",
        # R21: dotenv accepts punctuation, spaces and multiline quoted values
        PASSWORD + "=photo(booth)2026",
        PASSWORD + "=a,b{c}[d]",
        SECRET + "=correct horse battery staple",
        SECRET + '="first line\nsecond line"',
        "export " + TOKEN + " = 'q(1), 2' # comment",
        PASSWORD + "=pa#ss",
    ],
)
def test_populated_assignment_forms_rejected_even_in_env_example(repo: Path, line: str) -> None:
    _stage(repo, ".env.example", "PHOTOBOOTH_INSTANCE=dummy\n" + line + "\n")
    result = _run(repo)
    assert result.returncode == 1
    assert "[secret-assignment]" in result.stderr


def test_placeholder_assignment_forms_pass(repo: Path) -> None:
    lines = [
        PASSWORD + "=",
        PASSWORD + " = ",
        SECRET + '=""',
        TOKEN + "=<fill in locally>",
        "X_" + "TOKEN = changeme",
        "Y_" + "SECRET=  # set on the booth PC only",
        "Z_" + "PASSWORD=${ADMIN_PASSWORD}",
    ]
    _stage(repo, ".env.example", "\n".join(lines) + "\n")
    result = _run(repo)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["deploy/settings.cfg", "notes/booth.txt", "docs/setup.md"])
def test_non_source_config_and_text_files_use_dotenv_rules(repo: Path, name: str) -> None:
    _stage(repo, name, PASSWORD + "=photo(booth)2026\n")
    result = _run(repo)
    assert result.returncode == 1
    assert "[secret-assignment]" in result.stderr


def test_source_files_still_reject_literal_secrets(repo: Path) -> None:
    _stage(repo, "settings.py", SECRET + ' = "abc123def456"\n')
    result = _run(repo)
    assert result.returncode == 1


def test_python_source_assigning_compiled_patterns_is_not_a_secret(repo: Path) -> None:
    source = "import re\n" + "GOOGLE_REFRESH_" + 'TOKEN = re.compile(r"1//x")\n'
    _stage(repo, "module.py", source)
    result = _run(repo)
    assert result.returncode == 0, result.stderr
