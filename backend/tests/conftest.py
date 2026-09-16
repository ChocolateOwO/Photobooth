"""Shared fixtures. Every test gets its own instance root under a Thai-named temp directory."""

from __future__ import annotations

import secrets
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.migrations import Migrator
from photobooth.main import KioskAppOptions, create_delivery_app, create_kiosk_app

THAI_SEGMENT = "ทดสอบ-งาน"


@pytest.fixture
def thai_root() -> Iterator[Path]:
    """A fresh directory under the system temp dir whose path contains Thai characters."""
    base = Path(tempfile.gettempdir()) / f"pb-{THAI_SEGMENT}-{secrets.token_hex(4)}"
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        _rmtree(base)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def make_settings(root: Path, **overrides: object) -> AppSettings:
    values: dict[str, object] = {
        "instance": "dummy",
        "profile": "test",
        "instance_root": root,
        "kiosk_host": "127.0.0.1",
        "kiosk_port": 18111,
        "delivery_host": "127.0.0.1",
        "delivery_port": 18113,
    }
    values.update(overrides)
    return AppSettings(**values)  # type: ignore[arg-type]


@pytest.fixture
def settings(thai_root: Path) -> AppSettings:
    return make_settings(thai_root)


@pytest.fixture
def container(settings: AppSettings) -> Iterator[Container]:
    Migrator(settings.db_path).upgrade("head")
    built = Container(settings)
    built.system_service.stamp_instance()
    try:
        yield built
    finally:
        built.close()


@pytest.fixture
def kiosk_client(container: Container) -> Iterator[TestClient]:
    app = create_kiosk_app(container.registry, KioskAppOptions())
    with TestClient(app, base_url="http://127.0.0.1:18111") as client:
        yield client


@pytest.fixture
def delivery_client() -> Iterator[TestClient]:
    with TestClient(create_delivery_app(), base_url="http://192.168.1.50:18113") as client:
        yield client
