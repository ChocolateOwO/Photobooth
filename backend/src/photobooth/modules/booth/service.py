"""Booth use cases: list the active event's frames for participants and plan a chosen frame."""

from __future__ import annotations

from typing import Protocol

from photobooth.modules.booth.domain import (
    ActiveEvent,
    BoothFrame,
    FrameDirectory,
    FrameMenu,
    FrameNotOfferedError,
    FramePlan,
    LayoutDirectory,
    NoActiveEventError,
    layout_label,
)


class PreviewRenderer(Protocol):
    """A rendered sample output (illustrated photos + frame) as JPEG bytes (blocking).

    Raises PreviewBusyError or PreviewFailedError.
    """

    def sample_output(self, frame_id: str) -> bytes: ...


class BoothService:
    def __init__(
        self,
        event: ActiveEvent,
        frames: FrameDirectory,
        layouts: LayoutDirectory,
        previews: PreviewRenderer,
    ) -> None:
        self._event = event
        self._frames = frames
        self._layouts = layouts
        self._previews = previews

    def menu(self) -> FrameMenu:
        """Every offered frame that still exists and has a known layout, in the admin's order."""
        offer = self._event.offer()
        if offer is None:
            raise NoActiveEventError()
        frames: list[BoothFrame] = []
        for frame_id in offer.frame_ids:
            frame = self._frames.describe(frame_id)
            if frame is None:
                continue
            facts = self._layouts.facts(frame.template_key, frame.template_version)
            if facts is None:
                continue
            plan = FramePlan(
                frame_id=frame.frame_id,
                template_key=frame.template_key,
                layout_label=layout_label(facts.width_in, facts.height_in),
                captures=facts.captures,
                outputs=facts.outputs,
                photos_per_output=facts.photos_per_output,
                output_capture_groups=facts.output_capture_groups,
            )
            frames.append(BoothFrame(frame.frame_id, frame.name, frame.sha256[:16], plan))
        return FrameMenu(
            frames=tuple(frames),
            allow_surprise_me=offer.allow_surprise_me and len(frames) >= 2,
            theme_tokens=offer.theme_tokens,
        )

    def _offered(self, frame_id: str) -> BoothFrame:
        for frame in self.menu().frames:
            if frame.frame_id == frame_id:
                return frame
        raise FrameNotOfferedError(frame_id)

    def choose(self, frame_id: str) -> FramePlan:
        """Confirm a participant's choice: only an offered frame, with its capture/output plan."""
        return self._offered(frame_id).plan

    def preview(self, frame_id: str) -> bytes:
        """The sample output of an offered frame (other library frames stay private)."""
        self._offered(frame_id)
        return self._previews.sample_output(frame_id)
