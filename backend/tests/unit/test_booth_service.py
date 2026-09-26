"""BoothService with fake ports: order, skipped frames, surprise, previews, start screen."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from photobooth.modules.booth.domain import (
    EventImage,
    EventOffer,
    FrameNotOfferedError,
    ImageNotSetError,
    LayoutFacts,
    NoActiveEventError,
    OfferedFrame,
    StartImageKind,
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
    """Valid frames per layout, in library order (the frames module's job)."""

    def __init__(self, known: dict[str, str]) -> None:
        self.known = known  # id -> template key

    def offered(self, layouts: Sequence[str]) -> list[OfferedFrame]:
        return [
            OfferedFrame(frame_id, frame_id.upper(), key, 1, "ab" * 32)
            for layout in layouts
            for frame_id, key in self.known.items()
            if key == layout
        ]


class Layouts:
    def facts(self, template_key: str, version: int) -> LayoutFacts | None:
        return STRIP if template_key == "strip_2x6" else None


class Previews:
    def __init__(self) -> None:
        self.rendered: list[str] = []

    def sample_output(self, frame_id: str) -> bytes:
        self.rendered.append(frame_id)
        return b"jpeg"


class Images:
    """Assets by id: (kind, bytes). Anything else is unavailable."""

    def __init__(self, known: dict[str, tuple[str, bytes]] | None = None) -> None:
        self.known = known or {}

    def version(self, asset_id: str, kind: StartImageKind) -> str | None:
        found = self.known.get(asset_id)
        return None if found is None or found[0] != kind else f"v-{asset_id}"

    def image(self, asset_id: str, kind: StartImageKind) -> EventImage | None:
        found = self.known.get(asset_id)
        if found is None or found[0] != kind:
            return None
        return EventImage(found[1], "image/png", f"v-{asset_id}")


def service(
    layouts: list[str],
    surprise: bool = True,
    offer: EventOffer | None = None,
    known: dict[str, str] | None = None,
) -> tuple[BoothService, Previews]:
    previews = Previews()
    offer = offer or EventOffer(layouts, surprise, {"background": "#000000"})
    frames = Frames(known or {"a": "strip_2x6", "b": "strip_2x6", "odd": "retired_layout"})
    images = Images({"logo1": ("logo", b"LOGO"), "bg1": ("background", b"BG")})
    return BoothService(Event(offer), frames, Layouts(), previews, images), previews


def test_offers_every_frame_of_the_sizes_and_skips_unknown_layouts() -> None:
    booth, _ = service(["strip_2x6", "retired_layout", "print_4x6"])
    menu = booth.menu()
    assert [f.frame_id for f in menu.frames] == ["a", "b"]
    assert menu.layouts == ["strip_2x6"]
    assert menu.allow_surprise_me is True
    assert menu.frames[0].plan.output_label == "2 strips"
    assert menu.frames[0].version == "ab" * 8


def test_surprise_needs_two_valid_frames() -> None:
    booth, _ = service(["strip_2x6"], known={"a": "strip_2x6", "odd": "retired_layout"})
    assert booth.menu().allow_surprise_me is False


def test_a_size_that_is_not_chosen_offers_nothing_and_countdown_reaches_the_booth() -> None:
    offer = EventOffer(["print_4x6"], True, {}, countdown_seconds=8)
    booth, _ = service([], offer=offer)
    menu = booth.menu()
    assert menu.frames == () and menu.layouts == [] and menu.allow_surprise_me is False
    assert menu.countdown_seconds == 8


def test_only_offered_frames_are_described_or_previewed() -> None:
    booth, previews = service(["strip_2x6"], known={"a": "strip_2x6", "c": "print_4x6"})
    menu = booth.menu()
    assert [frame.frame_id for frame in menu.frames] == ["a"]
    assert menu.frames[0].plan.captures == 6
    assert booth.preview("a") == b"jpeg"
    with pytest.raises(FrameNotOfferedError):
        booth.preview("c")  # a size the event does not offer
    assert previews.rendered == ["a"]


def test_no_active_event() -> None:
    booth = BoothService(Event(None), Frames({}), Layouts(), Previews(), Images())
    with pytest.raises(NoActiveEventError):
        booth.menu()
    with pytest.raises(NoActiveEventError):
        booth.start_image("logo")


def test_layout_labels() -> None:
    assert layout_label(2, 6) == "2×6"
    assert layout_label(3.0, 4.0) == "3×4"
    assert layout_label(3.5, 5) == "3.5×5"


def test_start_screen_has_the_start_text_and_image_versions_only() -> None:
    offer = EventOffer(["strip_2x6"], False, {}, "  Let's go ", "logo1", "bg1")
    booth, _ = service([], offer=offer)
    screen = booth.menu().start_screen
    assert (screen.start_text, screen.logo_version, screen.background_version) == (
        "Let's go",
        "v-logo1",
        "v-bg1",
    )
    assert booth.start_image("logo").data == b"LOGO"
    assert booth.start_image("background").data == b"BG"


def test_start_screen_falls_back_without_images_or_text() -> None:
    # No logo, a background that no longer exists, a logo id that is really a background.
    for logo, background in ((None, "gone"), ("bg1", None)):
        offer = EventOffer(["strip_2x6"], False, {}, "   ", logo, background)
        booth, _ = service([], offer=offer)
        screen = booth.menu().start_screen
        assert screen.start_text == "Start"
        assert (screen.logo_version, screen.background_version) == (None, None)
        kinds: tuple[StartImageKind, ...] = ("logo", "background")
        for kind in kinds:
            with pytest.raises(ImageNotSetError):
                booth.start_image(kind)
