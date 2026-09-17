"""Rendering use cases."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from concurrent.futures import Future

from photobooth.modules.rendering.domain import (
    CaptureRef,
    CaptureSource,
    PhotoRenderer,
    RenderedOutput,
    RenderError,
    RenderJob,
    RenderScheduler,
    SampleImageFactory,
    TemplateLookup,
    plan_outputs,
)
from photobooth.modules.templates.domain import PhotoTemplate


class RenderService:
    def __init__(
        self,
        renderer: PhotoRenderer,
        templates: TemplateLookup,
        samples: SampleImageFactory,
        scheduler: RenderScheduler,
    ) -> None:
        self._renderer = renderer
        self._templates = templates
        self._samples = samples
        self._scheduler = scheduler
        self._sample_cache: dict[tuple[str, int, int], Future[RenderedOutput]] = {}
        self._sample_lock = threading.Lock()

    def render_session(
        self,
        template: PhotoTemplate,
        captures: Sequence[CaptureRef],
        source: CaptureSource,
        frame_png: bytes | None = None,
        mirror: bool = False,
    ) -> list[RenderedOutput]:
        """Render every output of a session; each capture appears in exactly one output."""
        outputs: list[RenderedOutput] = []
        for plan in plan_outputs(template, captures):
            images = {capture_id: source.read(capture_id) for capture_id in plan.capture_ids}
            outputs.append(
                self._renderer.render(
                    RenderJob(
                        template=template,
                        plan=plan,
                        images=images,
                        frame_png=frame_png,
                        mirror=mirror,
                    )
                )
            )
        return outputs

    def render_sample(
        self, key: str, output_index: int, version: int | None = None
    ) -> Future[RenderedOutput]:
        """Preview with numbered placeholder photos (shot N shows the number N).

        Samples are immutable per template version and output, so each is rendered once on the
        render queue and shared by concurrent and later requests (single-flight cache).
        Raises TemplateNotFoundError / RenderError immediately, RenderBusyError when the queue is
        full; the returned future carries rendering failures.
        """
        template = self._templates.get(key, version)
        if not 1 <= output_index <= template.outputs_per_session:
            raise RenderError(f"{key} has outputs 1..{template.outputs_per_session}")
        cache_key = (template.key, template.version, output_index)
        with self._sample_lock:
            cached = self._sample_cache.get(cache_key)
            if cached is not None:
                return cached
            future = self._scheduler.submit(lambda: self._render_one_sample(template, output_index))
            self._sample_cache[cache_key] = future
        future.add_done_callback(lambda done: self._forget_failure(cache_key, done))
        return future

    def _render_one_sample(self, template: PhotoTemplate, output_index: int) -> RenderedOutput:
        captures = [
            CaptureRef(capture_id=f"sample-{shot}", shot_index=shot)
            for shot in range(1, template.captures_per_session + 1)
        ]
        plan = plan_outputs(template, captures)[output_index - 1]
        source = _SampleSource(self._samples)
        images = {capture_id: source.read(capture_id) for capture_id in plan.capture_ids}
        return self._renderer.render(RenderJob(template=template, plan=plan, images=images))

    def _forget_failure(
        self, cache_key: tuple[str, int, int], done: Future[RenderedOutput]
    ) -> None:
        if done.cancelled() or done.exception() is not None:
            with self._sample_lock:
                if self._sample_cache.get(cache_key) is done:
                    del self._sample_cache[cache_key]


class _SampleSource:
    def __init__(self, samples: SampleImageFactory) -> None:
        self._samples = samples

    def read(self, capture_id: str) -> bytes:
        return self._samples.sample_capture(int(capture_id.removeprefix("sample-")))
