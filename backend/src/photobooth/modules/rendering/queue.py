"""Single render worker with bounded admission (the plan's "max concurrent renders 1 (queue)")."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from photobooth.modules.rendering.domain import RenderBusyError


class RenderQueue:
    """Runs render jobs one at a time on a dedicated thread, never in the web request pool.

    At most `max_pending` jobs may be queued or running; further submissions fail fast with
    RenderBusyError so a burst of requests can not build an unbounded backlog.
    """

    def __init__(self, max_pending: int = 4) -> None:
        if max_pending < 1:
            raise ValueError("max_pending must be >= 1")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="photobooth-render")
        self._max_pending = max_pending
        self._pending = 0
        self._lock = threading.Lock()

    @property
    def pending(self) -> int:
        with self._lock:
            return self._pending

    def submit[T](self, job: Callable[[], T]) -> Future[T]:
        with self._lock:
            if self._pending >= self._max_pending:
                raise RenderBusyError(f"render queue is full ({self._max_pending} jobs)")
            self._pending += 1
        try:
            future = self._executor.submit(job)
        except BaseException:
            with self._lock:
                self._pending -= 1
            raise
        future.add_done_callback(self._release)
        return future

    def _release(self, _future: Future[Any]) -> None:
        with self._lock:
            self._pending -= 1

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
