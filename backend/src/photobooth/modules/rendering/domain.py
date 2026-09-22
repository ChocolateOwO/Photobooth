"""Rendering domain: output planning (pure) and renderer ports. No image library imports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Protocol

from photobooth.modules.templates.domain import PhotoTemplate, SlotDefinition

JPEG_MEDIA_TYPE = "image/jpeg"


class RenderError(Exception):
    """Inputs can not be rendered (wrong capture set, bad image, bad frame)."""


class RenderBusyError(Exception):
    """The render queue is full; try again shortly."""


@dataclass(frozen=True)
class CaptureRef:
    """A successful capture of a session. `shot_index` is 1-based in capture order."""

    capture_id: str
    shot_index: int


@dataclass(frozen=True)
class SlotAssignment:
    slot: SlotDefinition
    capture: CaptureRef


@dataclass(frozen=True)
class OutputPlan:
    output_index: int
    template_key: str
    template_version: int
    assignments: tuple[SlotAssignment, ...]

    @property
    def capture_ids(self) -> tuple[str, ...]:
        return tuple(a.capture.capture_id for a in self.assignments)


def plan_outputs(template: PhotoTemplate, captures: Sequence[CaptureRef]) -> list[OutputPlan]:
    """Map a session's captures onto the template's outputs.

    Requires exactly `captures_per_session` captures with shot indexes 1..N and unique ids. Every
    capture is placed exactly once across all outputs (2x6: strip 1 = shots 1-3, strip 2 = 4-6).
    """
    if len(captures) != template.captures_per_session:
        raise RenderError(
            f"{template.key} needs {template.captures_per_session} captures, got {len(captures)}"
        )
    by_shot = {c.shot_index: c for c in captures}
    if sorted(by_shot) != list(range(1, template.captures_per_session + 1)):
        raise RenderError("captures must have shot indexes 1..N exactly once")
    if len({c.capture_id for c in captures}) != len(captures):
        raise RenderError("the same capture can not be used for two shots")

    plans = [
        OutputPlan(
            output_index=output_index,
            template_key=template.key,
            template_version=template.version,
            assignments=tuple(
                SlotAssignment(slot=slot, capture=by_shot[shot])
                for slot, shot in zip(template.slots, group, strict=True)
            ),
        )
        for output_index, group in enumerate(template.output_capture_groups, start=1)
    ]
    used = [capture_id for plan in plans for capture_id in plan.capture_ids]
    if len(used) != len(set(used)) or set(used) != {c.capture_id for c in captures}:
        raise RenderError("internal: output plan reuses or drops a capture")
    return plans


@dataclass(frozen=True)
class RenderJob:
    template: PhotoTemplate
    plan: OutputPlan
    images: Mapping[str, bytes]  # capture_id -> encoded image
    frame_png: bytes | None = None
    mirror: bool = False


@dataclass(frozen=True)
class RenderedOutput:
    output_index: int
    data: bytes
    media_type: str
    width: int
    height: int
    dpi: int
    capture_ids: tuple[str, ...]


class PhotoRenderer(ABC):
    @abstractmethod
    def render(self, job: RenderJob) -> RenderedOutput: ...


class CaptureSource(Protocol):
    """Returns the stored original image bytes for a capture."""

    def read(self, capture_id: str) -> bytes: ...


class TemplateLookup(Protocol):
    def get(self, key: str, version: int | None = None) -> PhotoTemplate: ...


class RenderScheduler(Protocol):
    """Runs render work off the request path with bounded admission (one render at a time)."""

    def submit[T](self, job: Callable[[], T]) -> Future[T]: ...


class SampleImageFactory(Protocol):
    """Synthetic numbered placeholder photos for previews (no real guest photos)."""

    def sample_capture(self, shot_index: int) -> bytes: ...

    def sample_photo(self, shot_index: int) -> bytes:
        """An illustrated stand-in photo (people on a backdrop) for frame previews."""
        ...
