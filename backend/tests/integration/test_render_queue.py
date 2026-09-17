"""P2-R03: one render at a time, bounded admission, cached samples, and the API stays responsive."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator

import httpx
import pytest

from photobooth.container import Container
from photobooth.main import KioskAppOptions, create_kiosk_app
from photobooth.modules.rendering.domain import (
    PhotoRenderer,
    RenderBusyError,
    RenderedOutput,
    RenderJob,
)
from photobooth.modules.rendering.queue import RenderQueue
from photobooth.modules.rendering.renderer import PillowPhotoRenderer, PillowSampleImageFactory
from photobooth.modules.rendering.service import RenderService


class SlowCountingRenderer(PhotoRenderer):
    """Real renderer plus a delay; records how many renders overlap."""

    def __init__(self, delay: float) -> None:
        self._inner = PillowPhotoRenderer()
        self._delay = delay
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def render(self, job: RenderJob) -> RenderedOutput:
        with self._lock:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self._delay)
            return self._inner.render(job)
        finally:
            with self._lock:
                self.active -= 1


def test_queue_runs_one_job_at_a_time_and_rejects_overflow() -> None:
    queue = RenderQueue(max_pending=2)
    running = threading.Event()
    release = threading.Event()
    overlap = []

    def job() -> int:
        overlap.append(running.is_set())
        running.set()
        release.wait(5)
        running.clear()
        return 1

    try:
        first = queue.submit(job)
        second = queue.submit(job)
        assert queue.pending == 2
        with pytest.raises(RenderBusyError):
            queue.submit(job)
        release.set()
        assert first.result(5) == 1 and second.result(5) == 1
        assert overlap == [False, False]
        deadline = time.monotonic() + 5
        while queue.pending and time.monotonic() < deadline:
            time.sleep(0.01)
        assert queue.pending == 0
        assert queue.submit(lambda: 2).result(5) == 2  # admission reopens after completion
    finally:
        release.set()
        queue.shutdown()


@pytest.fixture
def slow_app(container: Container) -> Iterator[tuple[httpx.AsyncClient, SlowCountingRenderer]]:
    renderer = SlowCountingRenderer(delay=0.4)
    queue = RenderQueue(max_pending=3)
    service = RenderService(renderer, container.template_service, PillowSampleImageFactory(), queue)
    container.registry.register(RenderService, service)
    app = create_kiosk_app(container.registry, KioskAppOptions())
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:18111", timeout=30
    )
    try:
        yield client, renderer
    finally:
        asyncio.run(client.aclose())
        queue.shutdown()


def test_concurrent_samples_render_serially_while_health_stays_fast(
    slow_app: tuple[httpx.AsyncClient, SlowCountingRenderer],
) -> None:
    client, renderer = slow_app
    paths = [
        "/api/render/samples/strip_2x6/1.jpg",
        "/api/render/samples/strip_2x6/2.jpg",
        "/api/render/samples/print_3x4/1.jpg",
    ]

    async def scenario() -> tuple[list[int], list[float], float]:
        started = time.monotonic()
        renders = [asyncio.create_task(client.get(path)) for path in paths]
        await asyncio.sleep(0.1)  # renders are queued / running now
        health_latencies = []
        for _ in range(5):
            t0 = time.monotonic()
            response = await client.get("/api/health")
            assert response.status_code == 200
            health_latencies.append(time.monotonic() - t0)
        statuses = [r.status_code for r in await asyncio.gather(*renders)]
        return statuses, health_latencies, time.monotonic() - started

    statuses, health_latencies, total = asyncio.run(scenario())
    assert statuses == [200, 200, 200]
    assert renderer.max_active == 1  # never more than one render at a time
    assert total >= 3 * 0.4 * 0.9  # the three renders were serialized
    assert max(health_latencies) < 0.35  # health answered while renders were still queued


def test_overflow_gets_503_and_cached_sample_is_not_re_rendered(
    slow_app: tuple[httpx.AsyncClient, SlowCountingRenderer],
) -> None:
    client, renderer = slow_app
    distinct = [
        "/api/render/samples/strip_2x6/1.jpg",
        "/api/render/samples/strip_2x6/2.jpg",
        "/api/render/samples/print_3x4/1.jpg",
        "/api/render/samples/print_4x6/1.jpg",
    ]

    async def burst() -> list[httpx.Response]:
        return list(await asyncio.gather(*(client.get(path) for path in distinct)))

    responses = asyncio.run(burst())
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 200, 200, 503]
    busy = next(r for r in responses if r.status_code == 503)
    assert busy.headers["retry-after"] == "2"

    calls_before = renderer.calls

    async def repeat() -> list[httpx.Response]:
        path = "/api/render/samples/strip_2x6/1.jpg"
        return list(await asyncio.gather(*(client.get(path) for _ in range(5))))

    repeated = asyncio.run(repeat())
    assert all(r.status_code == 200 for r in repeated)
    assert len({r.content for r in repeated}) == 1
    assert renderer.calls == calls_before  # served from the sample cache
