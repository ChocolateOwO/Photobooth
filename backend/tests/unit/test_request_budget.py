"""The per-client request budget of the delivery listener stays bounded (Codex P8-008)."""

from __future__ import annotations

from photobooth.modules.delivery.service import RequestBudget


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_client_over_its_limit_is_refused_until_its_window_passes() -> None:
    clock = Clock()
    budget = RequestBudget(limit=3, window_seconds=60, monotonic=clock)
    assert [budget.allow("phone") for _ in range(4)] == [True, True, True, False]
    assert budget.retry_after("phone") == 61
    clock.now = 61
    assert budget.allow("phone")


def test_quiet_clients_are_forgotten_so_memory_stays_bounded() -> None:
    clock = Clock()
    budget = RequestBudget(limit=5, window_seconds=60, monotonic=clock)
    for n in range(RequestBudget._MAX_CLIENTS):
        assert budget.allow(f"10.0.{n // 256}.{n % 256}")
    assert budget.clients == RequestBudget._MAX_CLIENTS
    clock.now = 120  # every one of them has gone quiet
    assert budget.allow("192.168.1.99")
    assert budget.clients == 1


def test_a_crowd_that_is_all_still_active_is_still_capped() -> None:
    clock = Clock()
    budget = RequestBudget(limit=5, window_seconds=60, monotonic=clock)
    for n in range(RequestBudget._MAX_CLIENTS * 2):
        clock.now = n / 1000
        budget.allow(f"client-{n}")
    assert budget.clients <= RequestBudget._MAX_CLIENTS
