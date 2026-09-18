"""The frontend test fixture of the theme catalogue matches the real backend catalogue."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "assets" / "export_theme_catalog.py"


def test_frontend_theme_fixture_is_current() -> None:
    spec = importlib.util.spec_from_file_location("export_theme_catalog", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.FIXTURE.read_text(encoding="utf-8") == module.render(), (
        "run scripts/assets/export_theme_catalog.py to refresh the frontend theme fixture"
    )
