"""Frame use cases: validate against a template, store, list, replace, rename, delete."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol

from photobooth.modules.frames.builtin import BuiltinFrame, builtin_frames
from photobooth.modules.frames.domain import (
    AssetStore,
    FrameAsset,
    FrameInVisitError,
    FrameNotFoundError,
    FrameReadOnlyError,
    FrameRepository,
    FrameStatus,
    FrameValidationError,
    FrameValidator,
    check_frame_name,
)
from photobooth.modules.templates.domain import PhotoTemplate, TemplateNotFoundError


class TemplateLookup(Protocol):
    def get(self, key: str, version: int | None = None) -> PhotoTemplate: ...


class FrameUsage(Protocol):
    """Which Event Profiles offer each photo size (implemented by the event_profiles module)."""

    def names_by_layout(self) -> dict[str, list[str]]: ...


class VisitsInProgress(Protocol):
    """Frames that booth visits already under way depend on (from the sessions module)."""

    def pinned_frames(self) -> set[str]: ...


class _AssetUsage:
    """Asset-level reference check: any frame row still pointing at the stored file."""

    def __init__(self, frames: FrameRepository) -> None:
        self._frames = frames

    def is_referenced(self, asset_id: str) -> bool:
        return self._frames.uses_asset(asset_id)


class FrameService:
    def __init__(
        self,
        repository: FrameRepository,
        assets: AssetStore,
        validator: FrameValidator,
        templates: TemplateLookup,
        usage: FrameUsage,
        visits: VisitsInProgress | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._repository = repository
        self._assets = assets
        self._validator = validator
        self._templates = templates
        self._usage = usage
        self._visits = visits
        self._clock = clock
        self._new_id = new_id
        self._asset_usage = _AssetUsage(repository)

    def _template(self, template_key: str) -> PhotoTemplate:
        try:
            return self._templates.get(template_key)
        except TemplateNotFoundError as exc:
            raise FrameValidationError(
                [f"Unknown photo layout '{template_key}'; choose one of the booth layouts."]
            ) from exc

    def upload(self, template_key: str, name: str, data: bytes) -> FrameAsset:
        """Validate the PNG against the layout, store the original bytes, record the frame."""
        template = self._template(template_key)
        frame_name = check_frame_name(name)
        report = self._validator.validate(data, template)
        asset = self._assets.upload("frame", data)
        now = self._clock()
        try:
            return self._repository.add(
                FrameAsset(
                    id=self._new_id(),
                    media_asset_id=asset.id,
                    template_key=template.key,
                    template_version=template.version,
                    name=frame_name,
                    status=FrameStatus.VALID,
                    report=report,
                    created_at=now,
                    updated_at=now,
                )
            )
        except FrameValidationError:
            # The row was refused (for example a duplicate name): do not leave the file behind.
            self._discard(asset.id)
            raise

    def list_frames(self, template_key: str | None = None) -> list[FrameAsset]:
        if template_key is not None:
            self._template(template_key)
        return self._repository.list_frames(template_key)

    def get(self, frame_id: str) -> FrameAsset:
        frame = self._repository.get(frame_id)
        if frame is None:
            raise FrameNotFoundError(frame_id)
        return frame

    def content(self, frame_id: str) -> tuple[FrameAsset, bytes]:
        frame = self.get(frame_id)
        _asset, data = self._assets.content(frame.media_asset_id)
        return frame, data

    def replace_file(self, frame_id: str, data: bytes) -> FrameAsset:
        """Swap in a corrected file. Profile selections keep working; old bytes stay untouched."""
        frame = self._custom(frame_id)
        self._not_in_a_visit(frame_id)
        template = self._templates.get(frame.template_key, frame.template_version)
        report = self._validator.validate(data, template)
        asset = self._assets.upload("frame", data)
        previous = frame.media_asset_id
        updated = self._repository.replace_file(frame_id, asset.id, report, self._clock())
        if previous != asset.id:
            self._discard(previous)  # the replaced file is removed when nothing else uses it
        return updated

    def rename(self, frame_id: str, name: str) -> FrameAsset:
        self._custom(frame_id)
        return self._repository.rename(frame_id, check_frame_name(name), self._clock())

    def delete(self, frame_id: str) -> None:
        """Remove an uploaded frame; it simply stops being offered (profiles choose sizes)."""
        frame = self._custom(frame_id)
        self._not_in_a_visit(frame_id)
        self._repository.delete(frame_id)
        self._discard(frame.media_asset_id)

    def _not_in_a_visit(self, frame_id: str) -> None:
        """A visit keeps the frame it was offered: its file may not change or vanish underneath."""
        if self._visits is not None and frame_id in self._visits.pinned_frames():
            raise FrameInVisitError()

    def _custom(self, frame_id: str) -> FrameAsset:
        """The frame, when the admin may change it (built-in frames are read-only)."""
        frame = self.get(frame_id)
        if frame.builtin:
            raise FrameReadOnlyError()
        return frame

    def ensure_builtin_files(self, catalog: tuple[BuiltinFrame, ...] | None = None) -> int:
        """Put the packaged PNG of every built-in frame into storage when it is missing.

        The rows come from migration 0004; the bytes ship with the app. Returns how many files
        were written. Packaged bytes that do not match the recorded sha256 raise instead of being
        stored, so a damaged package is noticed at start-up.
        """
        written = 0
        for builtin in catalog if catalog is not None else builtin_frames():
            frame = self._repository.get(builtin.id)
            if frame is None or not frame.builtin:
                continue
            if self._assets.ensure_stored(frame.media_asset_id, builtin.read()):
                written += 1
        return written

    def _discard(self, asset_id: str) -> None:
        """Delete the stored file when no frame and no Event Profile point at it any more."""
        self._assets.discard_if_unused(asset_id, self._asset_usage)

    def usage(self) -> dict[str, list[str]]:
        """frame id -> Event Profiles offering its photo size (shown on the Frames page)."""
        by_layout = self._usage.names_by_layout()
        return {
            frame.id: by_layout.get(frame.template_key, [])
            for frame in self._repository.list_frames()
        }

    def offered_frames(self, layouts: Sequence[str]) -> list[FrameAsset]:
        """Every valid frame of these layouts whose template still exists, in a stable order:
        the layouts in the given order, then built-in frames first and names A-Z."""
        offered: list[FrameAsset] = []
        for layout in layouts:
            for frame in self._repository.list_frames(layout):
                if frame.status is not FrameStatus.VALID:
                    continue
                try:
                    self._templates.get(frame.template_key, frame.template_version)
                except TemplateNotFoundError:
                    continue
                offered.append(frame)
        return offered

    def valid_frame_count(self, layouts: Sequence[str]) -> int:
        """Port for the event_profiles module: how many frames the booth would offer."""
        return len(self.offered_frames(layouts))
