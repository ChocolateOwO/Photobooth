from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from photobooth.core.errors import InstanceGuardError
from photobooth.core.instance_guard import InstanceGuard
from tests.conftest import make_settings


class FakeMeta:
    def __init__(self, instance: str | None) -> None:
        self._instance = instance

    def read_instance(self) -> str | None:
        return self._instance


def _check(root: Path, **overrides: object) -> None:
    InstanceGuard(make_settings(root, **overrides)).check_static()


def _assert_fails(check: str, root: Path, **overrides: object) -> None:
    with pytest.raises(InstanceGuardError) as info:
        _check(root, **overrides)
    assert info.value.check == check


def test_valid_test_profile_passes(thai_root: Path) -> None:
    _check(thai_root)


def test_valid_dummy_dev_instance_passes(thai_root: Path) -> None:
    root = thai_root / "Dummy"
    root.mkdir()
    _check(
        root,
        profile="dev",
        kiosk_port=8111,
        delivery_port=8113,
        ui_port=5191,
        delivery_host="0.0.0.0",
    )


def test_dummy_dev_requires_its_ui_port(thai_root: Path) -> None:
    root = thai_root / "Dummy"
    root.mkdir()
    base = {"profile": "dev", "kiosk_port": 8111, "delivery_port": 8113}
    _assert_fails("ports", root, **base)  # ui port missing
    _assert_fails("ports", root, **base, ui_port=5192)  # e2e ui port


def test_rejects_profile_not_allowed_for_instance(thai_root: Path) -> None:
    _assert_fails("profile", thai_root, instance="main", profile="dev")
    _assert_fails("profile", thai_root, instance="dummy", profile="prod")


def test_rejects_wrong_instance_root_name(thai_root: Path) -> None:
    root = thai_root / "Main"
    root.mkdir()
    _assert_fails("instance_root", root, profile="dev", kiosk_port=8111, delivery_port=8113)


def test_rejects_test_profile_outside_temp_dir(tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = Path(__file__).resolve().parents[2] / "never-created-root"
    _assert_fails("instance_root", outside)
    del tmp_path_factory


def test_rejects_db_path_outside_root(thai_root: Path) -> None:
    other = thai_root.parent / "someone-else" / "photobooth.sqlite"
    _assert_fails("path_containment", thai_root, db_path=other)


def test_rejects_parent_traversal(thai_root: Path) -> None:
    _assert_fails("path_containment", thai_root, storage_dir=Path("data/../../escape"))


def test_rejects_junction_escape(thai_root: Path) -> None:
    root = thai_root / "instance"
    outside = thai_root / "outside-target"
    root.mkdir()
    outside.mkdir()
    link = root / "data"
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(outside, target_is_directory=True)
    assert link.exists()
    _assert_fails("path_containment", root)


@pytest.mark.parametrize(
    ("instance", "profile", "kiosk", "delivery"),
    [
        ("dummy", "dev", 8121, 8123),  # Main's ports
        ("dummy", "dev", 8112, 8114),  # E2E ports
        ("dummy", "e2e", 8111, 8113),
    ],
)
def test_rejects_port_mismatch(
    thai_root: Path, instance: str, profile: str, kiosk: int, delivery: int
) -> None:
    root = thai_root / "Dummy" if profile == "dev" else thai_root
    root.mkdir(exist_ok=True)
    _assert_fails(
        "ports", root, instance=instance, profile=profile, kiosk_port=kiosk, delivery_port=delivery
    )


def test_rejects_same_kiosk_and_delivery_port(thai_root: Path) -> None:
    _assert_fails("ports", thai_root, kiosk_port=18000, delivery_port=18000)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "localhost", "::"])
def test_rejects_non_loopback_kiosk_bind(thai_root: Path, host: str) -> None:
    _assert_fails("bind", thai_root, kiosk_host=host)


def test_accepts_ipv6_loopback_kiosk(thai_root: Path) -> None:
    _check(thai_root, kiosk_host="::1")


def test_database_stamp_must_match_instance(thai_root: Path) -> None:
    guard = InstanceGuard(make_settings(thai_root))
    guard.check_database(FakeMeta("dummy"))
    with pytest.raises(InstanceGuardError, match="belongs to instance 'main'"):
        guard.check_database(FakeMeta("main"))
    with pytest.raises(InstanceGuardError, match="no instance stamp"):
        guard.check_database(FakeMeta(None))
