from __future__ import annotations

from pathlib import Path

from photobooth.core.kiosk_pairing import (
    DeviceCredentialRegistry,
    FilePairingCodeStore,
    PairingService,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _service(
    root: Path,
) -> tuple[PairingService, FilePairingCodeStore, DeviceCredentialRegistry, FakeClock]:
    store = FilePairingCodeStore(root / "runtime")
    registry = DeviceCredentialRegistry()
    clock = FakeClock()
    return PairingService(store, registry, clock=clock, ttl_seconds=60), store, registry, clock


def test_code_is_published_to_runtime_file_and_single_use(thai_root: Path) -> None:
    service, store, registry, _ = _service(thai_root)
    assert service.rotate()
    code = store.path.read_text(encoding="utf-8")
    assert len(code) >= 40

    credential = service.consume(code)
    assert credential is not None
    assert registry.verify(credential)
    assert not store.path.exists()
    assert service.consume(code) is None


def test_expired_code_is_rejected(thai_root: Path) -> None:
    service, store, _, clock = _service(thai_root)
    service.rotate()
    code = store.path.read_text(encoding="utf-8")
    clock.now += 61
    assert service.consume(code) is None


def test_wrong_or_empty_code_rejected(thai_root: Path) -> None:
    service, store, _, _ = _service(thai_root)
    service.rotate()
    assert service.consume("not-the-code") is None
    assert service.consume("") is None
    assert service.consume(None) is None
    # A wrong guess does not burn the real code.
    assert service.consume(store.path.read_text(encoding="utf-8")) is not None


def test_rotation_invalidates_previous_code(thai_root: Path) -> None:
    service, store, _, clock = _service(thai_root)
    service.rotate()
    first = store.path.read_text(encoding="utf-8")
    clock.now += 2
    service.rotate()
    second = store.path.read_text(encoding="utf-8")
    assert first != second
    assert service.consume(first) is None
    assert service.consume(second) is not None


def test_rotation_is_rate_limited(thai_root: Path) -> None:
    service, _, _, clock = _service(thai_root)
    assert service.rotate()
    assert not service.rotate()
    clock.now += 1.5
    assert service.rotate()


def test_credentials_do_not_survive_a_new_registry() -> None:
    old = DeviceCredentialRegistry()
    credential = old.issue()
    assert old.verify(credential)
    assert not DeviceCredentialRegistry().verify(credential)
    assert not old.verify(None)
    assert not old.verify("forged")


def test_shutdown_clears_code_file(thai_root: Path) -> None:
    service, store, _, _ = _service(thai_root)
    service.rotate()
    service.shutdown()
    assert not store.path.exists()
