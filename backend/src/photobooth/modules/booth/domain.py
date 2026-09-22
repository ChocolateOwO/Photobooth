"""Booth domain: what participants may choose and the plan a chosen frame implies.

Only what the active Event Profile offers is visible here, in its order. Nothing about files,
storage or whether a frame is built-in or uploaded reaches participants.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class BoothError(Exception):
    """Base error for participant booth operations."""


class NoActiveEventError(BoothError):
    def __init__(self) -> None:
        super().__init__("no event is active on this booth yet")


class PreviewBusyError(BoothError):
    """The renderer is busy; the participant screen retries shortly."""


class PreviewFailedError(BoothError):
    """The sample output could not be rendered."""


class FrameNotOfferedError(BoothError):
    def __init__(self, frame_id: str) -> None:
        super().__init__(f"frame {frame_id} is not offered by the active event")


@dataclass(frozen=True)
class FramePlan:
    """What choosing this frame means for the session: captures and outputs."""

    frame_id: str
    template_key: str
    layout_label: str  # e.g. "2x6" written with a multiplication sign
    captures: int
    outputs: int
    photos_per_output: int
    output_capture_groups: tuple[tuple[int, ...], ...]

    @property
    def output_label(self) -> str | None:
        """Only mentioned when a session makes more than one output."""
        if self.outputs <= 1:
            return None
        noun = "strips" if self.template_key.startswith("strip") else "prints"
        return f"{self.outputs} {noun}"


@dataclass(frozen=True)
class BoothFrame:
    frame_id: str
    name: str
    version: str  # changes when the frame file changes (cache key for its preview)
    plan: FramePlan


@dataclass(frozen=True)
class FrameMenu:
    frames: tuple[BoothFrame, ...]
    allow_surprise_me: bool  # already false when fewer than two frames are offered
    theme_tokens: Mapping[str, str]

    @property
    def layouts(self) -> list[str]:
        seen: list[str] = []
        for frame in self.frames:
            if frame.plan.template_key not in seen:
                seen.append(frame.plan.template_key)
        return seen


@dataclass(frozen=True)
class EventOffer:
    """The active profile's participant-facing choices (from the event_profiles module)."""

    frame_ids: Sequence[str]
    allow_surprise_me: bool
    theme_tokens: Mapping[str, str]


@dataclass(frozen=True)
class OfferedFrame:
    """A frame as the booth may describe it (from the frames module)."""

    frame_id: str
    name: str
    template_key: str
    template_version: int
    sha256: str


@dataclass(frozen=True)
class LayoutFacts:
    width_in: float
    height_in: float
    captures: int
    outputs: int
    photos_per_output: int
    output_capture_groups: tuple[tuple[int, ...], ...]


class ActiveEvent(Protocol):
    def offer(self) -> EventOffer | None: ...


class FrameDirectory(Protocol):
    def describe(self, frame_id: str) -> OfferedFrame | None: ...


class LayoutDirectory(Protocol):
    def facts(self, template_key: str, version: int) -> LayoutFacts | None: ...


def layout_label(width_in: float, height_in: float) -> str:
    def number(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:g}"

    return f"{number(width_in)}\u00d7{number(height_in)}"  # 2 by 6 style label
