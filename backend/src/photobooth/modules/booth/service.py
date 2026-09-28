"""Booth use cases: the start screen and frames of the active event, and a chosen frame's plan."""

from __future__ import annotations

from typing import Protocol

from photobooth.modules.booth.domain import (
    DEFAULT_START_TEXT,
    ActiveEvent,
    BoothFrame,
    EventImage,
    EventImages,
    EventOffer,
    FrameDirectory,
    FrameMenu,
    FrameNotOfferedError,
    FramePlan,
    ImageNotSetError,
    LayoutDirectory,
    NoActiveEventError,
    StartImageKind,
    StartScreen,
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
        images: EventImages,
    ) -> None:
        self._event = event
        self._frames = frames
        self._layouts = layouts
        self._previews = previews
        self._images = images

    def _offer(self, profile_id: str | None = None) -> EventOffer:
        # No profile named: the event the booth is running. Named: a saved profile the organizer
        # is trying from Admin, which is read but never activated.
        offer = self._event.offer(profile_id)
        if offer is None:
            raise NoActiveEventError()
        return offer

    @staticmethod
    def _asset_of(offer: EventOffer, kind: StartImageKind) -> str | None:
        return offer.logo_asset_id if kind == "logo" else offer.background_asset_id

    def _start_screen(self, offer: EventOffer) -> StartScreen:
        def version(kind: StartImageKind) -> str | None:
            asset_id = self._asset_of(offer, kind)
            return None if asset_id is None else self._images.version(asset_id, kind)

        return StartScreen(
            start_text=offer.start_button_text.strip() or DEFAULT_START_TEXT,
            logo_version=version("logo"),
            background_version=version("background"),
        )

    def start_image(self, kind: StartImageKind) -> EventImage:
        """The active event's own logo or background; nothing else can be fetched this way."""
        offer = self._offer()
        asset_id = self._asset_of(offer, kind)
        image = None if asset_id is None else self._images.image(asset_id, kind)
        if image is None:
            raise ImageNotSetError(kind)
        return image

    def menu(self, profile_id: str | None = None) -> FrameMenu:
        """Every valid frame of the event's photo sizes whose layout is known, in stable order."""
        offer = self._offer(profile_id)
        frames: list[BoothFrame] = []
        for frame in self._frames.offered(offer.layouts):
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
                photo_slot=facts.photo_slot,
            )
            frames.append(BoothFrame(frame.frame_id, frame.name, frame.sha256[:16], plan))
        return FrameMenu(
            frames=tuple(frames),
            allow_surprise_me=offer.allow_surprise_me and len(frames) >= 2,
            theme_tokens=offer.theme_tokens,
            start_screen=self._start_screen(offer),
            countdown_seconds=offer.countdown_seconds,
        )

    def _offered(self, frame_id: str) -> BoothFrame:
        for frame in self.menu().frames:
            if frame.frame_id == frame_id:
                return frame
        raise FrameNotOfferedError(frame_id)

    def preview(self, frame_id: str) -> bytes:
        """The sample output of an offered frame (other library frames stay private)."""
        self._offered(frame_id)
        return self._previews.sample_output(frame_id)
