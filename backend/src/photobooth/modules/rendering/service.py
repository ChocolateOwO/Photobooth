"""Rendering use cases."""

from __future__ import annotations

from collections.abc import Sequence

from photobooth.modules.rendering.domain import (
    CaptureRef,
    CaptureSource,
    PhotoRenderer,
    RenderedOutput,
    RenderError,
    RenderJob,
    SampleImageFactory,
    TemplateLookup,
    plan_outputs,
)
from photobooth.modules.templates.domain import PhotoTemplate


class RenderService:
    def __init__(
        self, renderer: PhotoRenderer, templates: TemplateLookup, samples: SampleImageFactory
    ) -> None:
        self._renderer = renderer
        self._templates = templates
        self._samples = samples

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
    ) -> RenderedOutput:
        """Preview with numbered placeholder photos (shot N shows the number N)."""
        template = self._templates.get(key, version)
        if not 1 <= output_index <= template.outputs_per_session:
            raise RenderError(f"{key} has outputs 1..{template.outputs_per_session}")
        captures = [
            CaptureRef(capture_id=f"sample-{shot}", shot_index=shot)
            for shot in range(1, template.captures_per_session + 1)
        ]
        source = _SampleSource(self._samples)
        return self.render_session(template, captures, source)[output_index - 1]


class _SampleSource:
    def __init__(self, samples: SampleImageFactory) -> None:
        self._samples = samples

    def read(self, capture_id: str) -> bytes:
        return self._samples.sample_capture(int(capture_id.removeprefix("sample-")))
