"""Event Profile use cases."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from photobooth.modules.event_profiles.domain import (
    NAME_MAX_LENGTH,
    AssetLookup,
    EventProfile,
    EventProfileRepository,
    FrameLookup,
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileSettings,
    ProfileValidationError,
    TemplateCatalog,
)


class EventProfileService:
    def __init__(
        self,
        repository: EventProfileRepository,
        assets: AssetLookup,
        templates: TemplateCatalog,
        frames: FrameLookup,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._repository = repository
        self._assets = assets
        self._templates = templates
        self._frames = frames
        self._clock = clock
        self._new_id = new_id

    def _validate(self, settings: ProfileSettings) -> ProfileSettings:
        normalized = replace(
            settings,
            name=" ".join(settings.name.split()),
            title=settings.title.strip(),
            subtitle=settings.subtitle.strip(),
            start_button_text=settings.start_button_text.strip(),
            theme=settings.theme.normalized(),
        )
        problems = normalized.problems()
        known_layouts = {t.key for t in self._templates.list_latest()}
        unknown = [key for key in normalized.enabled_layouts if key not in known_layouts]
        if unknown:
            problems.append(f"unknown layouts: {', '.join(unknown)}")
        if normalized.logo_asset_id is not None and not self._assets.exists(
            normalized.logo_asset_id, "logo"
        ):
            problems.append("logo_asset_id does not refer to an uploaded logo")
        if normalized.background_asset_id is not None and not self._assets.exists(
            normalized.background_asset_id, "background"
        ):
            problems.append("background_asset_id does not refer to an uploaded background")
        for template_key, frame_id in normalized.frame_selections:
            belongs_to = self._frames.frame_template(frame_id)
            if belongs_to is None:
                problems.append(f"the frame chosen for {template_key} does not exist")
            elif belongs_to != template_key:
                problems.append(
                    f"that frame belongs to the {belongs_to} layout, not {template_key}"
                )
        if problems:
            raise ProfileValidationError(problems)
        return normalized

    def names_using_frame(self, frame_id: str) -> list[str]:
        """Port for the frames module: live profiles that still select this frame."""
        return self._repository.names_using_frame(frame_id)

    def list_profiles(self, include_deleted: bool = False) -> list[EventProfile]:
        return self._repository.list_profiles(include_deleted)

    def get(self, profile_id: str) -> EventProfile:
        profile = self._repository.get(profile_id)
        if profile is None:
            raise ProfileNotFoundError(profile_id)
        return profile

    def get_active(self) -> EventProfile | None:
        return self._repository.get_active()

    def create(self, settings: ProfileSettings) -> EventProfile:
        now = self._clock()
        return self._repository.add(
            EventProfile(
                id=self._new_id(),
                settings=self._validate(settings),
                is_active=False,
                revision=1,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
        )

    def update(
        self, profile_id: str, settings: ProfileSettings, expected_revision: int
    ) -> EventProfile:
        current = self.get(profile_id)
        if current.deleted:
            raise ProfileConflictError("a deleted profile can not be edited; restore it first")
        return self._repository.update(
            profile_id, self._validate(settings), expected_revision, self._clock()
        )

    def duplicate(self, profile_id: str, name: str | None = None) -> EventProfile:
        source = self.get(profile_id)
        if source.deleted:
            raise ProfileConflictError("a deleted profile can not be duplicated")
        new_name = name if name is not None else self._copy_name(source.settings.name)
        return self.create(replace(source.settings, name=new_name))

    def _copy_name(self, base: str) -> str:
        taken = {p.settings.name_key for p in self._repository.list_profiles(include_deleted=False)}
        for n in range(1, 1000):
            suffix = " (copy)" if n == 1 else f" (copy {n})"
            # Reserve room for the whole suffix so truncation never drops it.
            candidate = " ".join(base.split())[: NAME_MAX_LENGTH - len(suffix)].rstrip() + suffix
            if ProfileSettings(name=candidate, title="x").name_key not in taken:
                return candidate
        raise ProfileConflictError("could not find a free copy name")

    def activate(self, profile_id: str) -> EventProfile:
        return self._repository.activate(profile_id, self._clock())

    def soft_delete(self, profile_id: str, expected_revision: int) -> EventProfile:
        return self._repository.soft_delete(profile_id, expected_revision, self._clock())

    def restore(self, profile_id: str) -> EventProfile:
        return self._repository.restore(profile_id, self._clock())
