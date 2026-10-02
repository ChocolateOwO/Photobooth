"""Event Profile use cases."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from photobooth.modules.event_profiles.domain import (
    NAME_MAX_LENGTH,
    NO_FRAMES_FOR_ACTIVE,
    NO_SIZES_FOR_ACTIVE,
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
        catalog = [t.key for t in self._templates.list_latest()]
        unknown = [key for key in normalized.enabled_layouts if key not in catalog]
        if unknown:
            problems.append(f"unknown photo sizes: {', '.join(unknown)}")
        # Stored in the template catalogue order, so the booth shows a stable order.
        normalized = replace(
            normalized,
            enabled_layouts=tuple(key for key in catalog if key in normalized.enabled_layouts),
        )
        if normalized.logo_asset_id is not None and not self._assets.exists(
            normalized.logo_asset_id, "logo"
        ):
            problems.append("logo_asset_id does not refer to an uploaded logo")
        if normalized.background_asset_id is not None and not self._assets.exists(
            normalized.background_asset_id, "background"
        ):
            problems.append("background_asset_id does not refer to an uploaded background")
        if problems:
            raise ProfileValidationError(problems)
        return normalized

    def names_by_layout(self) -> dict[str, list[str]]:
        """Port for the frames module: layout -> names of the profiles offering that size."""
        return self._repository.names_by_layout()

    def default_layouts(self) -> tuple[str, ...]:
        """A new profile offers every photo size (so every frame, including later uploads)."""
        return tuple(t.key for t in self._templates.list_latest())

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
        if current.is_active and not settings.enabled_layouts:
            raise ProfileValidationError([NO_SIZES_FOR_ACTIVE])
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
        profile = self.get(profile_id)
        if not profile.deleted:
            if not profile.settings.enabled_layouts:
                raise ProfileConflictError(NO_SIZES_FOR_ACTIVE)
            if self._frames.valid_frame_count(profile.settings.enabled_layouts) == 0:
                raise ProfileConflictError(NO_FRAMES_FOR_ACTIVE)
        return self._repository.activate(profile_id, self._clock())

    def soft_delete(self, profile_id: str, expected_revision: int) -> EventProfile:
        return self._repository.soft_delete(profile_id, expected_revision, self._clock())

    def remove_deleted(self, profile_id: str) -> bool:
        """Permanently delete a profile that was deleted (retention asks, after its visits)."""
        return self._repository.remove_deleted(profile_id)

    def restore(self, profile_id: str) -> EventProfile:
        return self._repository.restore(profile_id, self._clock())
