"""BoothService with fake ports: order, skipped frames, surprise rule, private previews."""

from __future__ import annotations

import pytest

from photobooth.modules.booth.domain import (
    EventOffer,
    FrameNotOfferedError,
    LayoutFacts,
    NoActiveEventError,
    OfferedFrame,
    layout_label,
)
from photobooth.modules.booth.service import BoothService

STRIP = LayoutFacts(2, 6, 6, 2, 3, ((1, 2, 3), (4, 5, 6)))


class Event:
    def __init__(self, offer: EventOffer | None) -> None:
        self.value = offer

    def offer(self) -> EventOffer | None:
        return self.value


class Frames:
    def __init__(self, known: dict[str, str]) -> None:
        self.known = known  # id -> template key

    def describe(self, frame_id: str) -> OfferedFrame | None:
        key = self.known.get(frame_id)
        return None if key is None else OfferedFrame(frame_id, frame_id.upper(), key, 1, "ab" * 32)


class Layouts:
    def facts(self, template_key: str, version: int) -> LayoutFacts | None:
        return STRIP if template_key == "strip_2x6" else None


class Previews:
    def __init__(self) -> None:
        self.rendered: list[str] = []

    def sample_output(self, frame_id: str) -> bytes:
        self.rendered.append(frame_id)
        return b"jpeg"


def service(frame_ids: list[str], surprise: bool = True) -> tuple[BoothService, Previews]:
    previews = Previews()
    offer = EventOffer(frame_ids, surprise, {"background": "#000000"})
    frames = Frames({"a": "strip_2x6", "b": "strip_2x6", "odd": "retired_layout"})
    return BoothService(Event(offer), frames, Layouts(), previews), previews


def test_keeps_order_and_skips_missing_or_unknown_layout_frames() -> None:
    booth, _ = service(["b", "gone", "odd", "a"])
    menu = booth.menu()
    assert [f.frame_id for f in menu.frames] == ["b", "a"]
    assert menu.layouts == ["strip_2x6"]
    assert menu.allow_surprise_me is True
    assert menu.frames[0].plan.output_label == "2 strips"
    assert menu.frames[0].version == "ab" * 8


def test_surprise_needs_two_valid_frames() -> None:
    booth, _ = service(["a", "gone"])
    assert booth.menu().allow_surprise_me is False


def test_only_offered_frames_can_be_chosen_or_previewed() -> None:
    booth, previews = service(["a"])
    assert booth.choose("a").captures == 6
    assert booth.preview("a") == b"jpeg"
    with pytest.raises(FrameNotOfferedError):
        booth.choose("b")
    with pytest.raises(FrameNotOfferedError):
        booth.preview("b")
    assert previews.rendered == ["a"]


def test_no_active_event() -> None:
    booth = BoothService(Event(None), Frames({}), Layouts(), Previews())
    with pytest.raises(NoActiveEventError):
        booth.menu()


def test_layout_labels() -> None:
    assert layout_label(2, 6) == "2×6"
    assert layout_label(3.0, 4.0) == "3×4"
    assert layout_label(3.5, 5) == "3.5×5"
