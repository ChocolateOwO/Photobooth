"""SQLAlchemy EventProfileRepository.

Invariants enforced by the database, not only by the service:
- at most one active profile (partial unique index on is_active where is_active = 1);
- live profile names are unique case-insensitively (partial unique index on name_key);
- a deleted profile is never active (check constraint);
- the countdown is a whole number of seconds from 1 to 10 (check constraint);
- logo/background rows can not be removed while a profile references them (FK RESTRICT).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    CursorResult,
    Engine,
    ForeignKey,
    Index,
    Integer,
    Result,
    String,
    Text,
    UniqueConstraint,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, sessionmaker

from photobooth.core.db import Base, UtcDateTime
from photobooth.modules.event_profiles.domain import (
    NO_SIZES_FOR_ACTIVE,
    DeliveryMode,
    EventProfile,
    EventProfileRepository,
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileSettings,
    ProfileValidationError,
    RetakeMode,
)
from photobooth.modules.themes.domain import EventTheme, ThemeSource


class EventProfileLayoutRow(Base):
    """A photo size (layout) participants may use in this profile, at its display position.

    Every valid frame of an enabled layout is offered at the booth, so frames are never linked to
    profiles one by one (uploading, renaming, replacing or deleting a frame needs no profile
    edit). The unique position keeps the order unambiguous.
    """

    __tablename__ = "event_profile_layouts"
    __table_args__ = (
        UniqueConstraint("profile_id", "position", name="uq_event_profile_layout_position"),
        CheckConstraint("position >= 0", name="ck_event_profile_layout_position"),
    )

    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    template_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class EventProfileRow(Base):
    __tablename__ = "event_profiles"
    __table_args__ = (
        CheckConstraint(
            "countdown_seconds BETWEEN 1 AND 10", name="ck_event_profiles_countdown_range"
        ),
        CheckConstraint(
            "inactivity_timeout_s BETWEEN 30 AND 900", name="ck_event_profiles_inactivity_range"
        ),
        CheckConstraint(
            "NOT (is_active = 1 AND deleted_at IS NOT NULL)",
            name="ck_event_profiles_deleted_not_active",
        ),
        CheckConstraint("revision >= 1", name="ck_event_profiles_revision_positive"),
        Index(
            "uq_event_profiles_live_name",
            "name_key",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_event_profiles_single_active",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(240), nullable=False)
    start_button_text: Mapped[str] = mapped_column(String(40), nullable=False)
    logo_asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=True
    )
    background_asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=True
    )
    theme: Mapped[str] = mapped_column(Text, nullable=False)  # JSON, see _theme_json
    countdown_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    mirror: Mapped[bool] = mapped_column(Boolean, nullable=False)
    inactivity_timeout_s: Mapped[int] = mapped_column(Integer, nullable=False)
    retake_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    delivery_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    allow_surprise_me: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    layouts: Mapped[list[EventProfileLayoutRow]] = relationship(
        order_by=EventProfileLayoutRow.position,
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def apply(self, settings: ProfileSettings) -> None:
        self.name = settings.name
        self.name_key = settings.name_key
        self.title = settings.title
        self.subtitle = settings.subtitle
        self.start_button_text = settings.start_button_text
        self.logo_asset_id = settings.logo_asset_id
        self.background_asset_id = settings.background_asset_id
        self.theme = _theme_json(settings.theme)
        self.countdown_seconds = settings.countdown_seconds
        self.mirror = settings.mirror
        self.inactivity_timeout_s = settings.inactivity_timeout_s
        self.retake_mode = settings.retake_mode.value
        self.delivery_mode = settings.delivery_mode.value
        self.allow_surprise_me = settings.allow_surprise_me

    def to_domain(self) -> EventProfile:
        return EventProfile(
            id=self.id,
            settings=ProfileSettings(
                name=self.name,
                title=self.title,
                subtitle=self.subtitle,
                start_button_text=self.start_button_text,
                logo_asset_id=self.logo_asset_id,
                background_asset_id=self.background_asset_id,
                theme=_theme_of(self.theme),
                enabled_layouts=tuple(row.template_key for row in self.layouts),
                allow_surprise_me=self.allow_surprise_me,
                countdown_seconds=self.countdown_seconds,
                mirror=self.mirror,
                inactivity_timeout_s=self.inactivity_timeout_s,
                retake_mode=RetakeMode(self.retake_mode),
                delivery_mode=DeliveryMode(self.delivery_mode),
            ),
            is_active=self.is_active,
            revision=self.revision,
            created_at=self.created_at,
            updated_at=self.updated_at,
            deleted_at=self.deleted_at,
        )


def _theme_json(theme: EventTheme) -> str:
    return json.dumps(
        {
            "tokens": dict(theme.tokens),
            "source": theme.source.value,
            "preset": theme.preset,
            "palette": list(theme.palette),
        },
        sort_keys=True,
    )


def _theme_of(raw: str) -> EventTheme:
    data = json.loads(raw)
    return EventTheme(
        tokens={str(k): str(v) for k, v in data["tokens"].items()},
        source=ThemeSource(data.get("source", ThemeSource.CUSTOM.value)),
        preset=data.get("preset"),
        palette=tuple(str(c) for c in data.get("palette", [])),
    )


def _rowcount(result: Result[Any]) -> int:
    return cast(CursorResult[Any], result).rowcount


def _layout_rows(profile_id: str, settings: ProfileSettings) -> list[EventProfileLayoutRow]:
    return [
        EventProfileLayoutRow(profile_id=profile_id, template_key=key, position=index)
        for index, key in enumerate(settings.enabled_layouts)
    ]


def _usage_name(row: EventProfileRow) -> str:
    return row.name if row.deleted_at is None else f"{row.name} (deleted)"


def _conflict(exc: IntegrityError) -> ProfileConflictError:
    message = str(exc.orig)
    if "name_key" in message:
        return ProfileConflictError("another live profile already uses this name")
    if "FOREIGN KEY" in message:
        return ProfileConflictError("a referenced asset does not exist")
    return ProfileConflictError("the change conflicts with the stored profiles")


class SqlEventProfileRepository(EventProfileRepository):
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def list_profiles(self, include_deleted: bool) -> list[EventProfile]:
        query = select(EventProfileRow).order_by(EventProfileRow.created_at, EventProfileRow.id)
        if not include_deleted:
            query = query.where(EventProfileRow.deleted_at.is_(None))
        with self._sessions() as session:
            return [row.to_domain() for row in session.scalars(query)]

    def get(self, profile_id: str) -> EventProfile | None:
        with self._sessions() as session:
            row = session.get(EventProfileRow, profile_id)
            return None if row is None else row.to_domain()

    def get_active(self) -> EventProfile | None:
        with self._sessions() as session:
            row = session.scalars(
                select(EventProfileRow).where(EventProfileRow.is_active.is_(True))
            ).first()
            return None if row is None else row.to_domain()

    def add(self, profile: EventProfile) -> EventProfile:
        row = EventProfileRow(
            id=profile.id,
            is_active=False,
            revision=profile.revision,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            deleted_at=None,
        )
        row.apply(profile.settings)
        row.layouts = _layout_rows(profile.id, profile.settings)
        try:
            with self._sessions.begin() as session:
                session.add(row)
        except IntegrityError as exc:
            raise _conflict(exc) from exc
        return self._require(profile.id)

    def update(
        self, profile_id: str, settings: ProfileSettings, expected_revision: int, at: datetime
    ) -> EventProfile:
        try:
            with self._sessions.begin() as session:
                # Write first: the conditional UPDATE takes SQLite's write lock at once, so a
                # concurrent writer can never interleave between the revision check and the change.
                changed = _rowcount(
                    session.execute(
                        update(EventProfileRow)
                        .where(
                            EventProfileRow.id == profile_id,
                            EventProfileRow.revision == expected_revision,
                            EventProfileRow.deleted_at.is_(None),
                        )
                        .values(revision=EventProfileRow.revision + 1, updated_at=at)
                        .execution_options(synchronize_session=False)
                    )
                )
                if changed != 1:
                    self._explain_miss(session, profile_id, expected_revision)
                row = session.get(EventProfileRow, profile_id, populate_existing=True)
                assert row is not None
                if row.is_active and not settings.enabled_layouts:
                    # Checked under the write lock, so no concurrent activation slips past it.
                    raise ProfileValidationError([NO_SIZES_FOR_ACTIVE])
                row.apply(settings)
                # The whole list (membership and order) is replaced in this one transaction.
                session.execute(
                    delete(EventProfileLayoutRow).where(
                        EventProfileLayoutRow.profile_id == profile_id
                    )
                )
                session.expire(row, ["layouts"])
                session.flush()
                if settings.enabled_layouts:
                    session.execute(
                        insert(EventProfileLayoutRow),
                        [
                            {"profile_id": profile_id, "template_key": key, "position": index}
                            for index, key in enumerate(settings.enabled_layouts)
                        ],
                    )
        except IntegrityError as exc:
            raise _conflict(exc) from exc
        return self._require(profile_id)

    def activate(self, profile_id: str, at: datetime) -> EventProfile:
        with self._sessions.begin() as session:
            # One transaction: clear the previous active profile, then activate the target. The
            # partial unique index guarantees a single active row even under concurrent callers.
            session.execute(
                update(EventProfileRow)
                .where(EventProfileRow.is_active.is_(True), EventProfileRow.id != profile_id)
                .values(is_active=False, updated_at=at)
                .execution_options(synchronize_session=False)
            )
            has_sizes = (
                select(EventProfileLayoutRow.template_key)
                .where(EventProfileLayoutRow.profile_id == profile_id)
                .exists()
            )
            changed = _rowcount(
                session.execute(
                    update(EventProfileRow)
                    .where(
                        EventProfileRow.id == profile_id,
                        EventProfileRow.deleted_at.is_(None),
                        has_sizes,
                    )
                    .values(is_active=True, updated_at=at)
                    .execution_options(synchronize_session=False)
                )
            )
            if changed != 1:
                existing = session.get(EventProfileRow, profile_id)
                if existing is None:
                    raise ProfileNotFoundError(profile_id)
                if existing.deleted_at is not None:
                    raise ProfileConflictError(
                        "a deleted profile can not be activated; restore it first"
                    )
                raise ProfileConflictError(NO_SIZES_FOR_ACTIVE)
        return self._require(profile_id)

    def soft_delete(self, profile_id: str, expected_revision: int, at: datetime) -> EventProfile:
        with self._sessions.begin() as session:
            changed = _rowcount(
                session.execute(
                    update(EventProfileRow)
                    .where(
                        EventProfileRow.id == profile_id,
                        EventProfileRow.revision == expected_revision,
                        EventProfileRow.deleted_at.is_(None),
                        EventProfileRow.is_active.is_(False),
                    )
                    .values(deleted_at=at, updated_at=at, revision=EventProfileRow.revision + 1)
                    .execution_options(synchronize_session=False)
                )
            )
            if changed != 1:
                existing = session.get(EventProfileRow, profile_id)
                if existing is not None and existing.deleted_at is None and existing.is_active:
                    raise ProfileConflictError(
                        "the active profile can not be deleted; activate another profile first"
                    )
                self._explain_miss(session, profile_id, expected_revision)
        return self._require(profile_id)

    def restore(self, profile_id: str, at: datetime) -> EventProfile:
        try:
            with self._sessions.begin() as session:
                changed = _rowcount(
                    session.execute(
                        update(EventProfileRow)
                        .where(
                            EventProfileRow.id == profile_id,
                            EventProfileRow.deleted_at.is_not(None),
                        )
                        .values(
                            deleted_at=None, updated_at=at, revision=EventProfileRow.revision + 1
                        )
                        .execution_options(synchronize_session=False)
                    )
                )
                if changed != 1:
                    if session.get(EventProfileRow, profile_id) is None:
                        raise ProfileNotFoundError(profile_id)
                    raise ProfileConflictError("the profile is not deleted")
        except IntegrityError as exc:
            raise _conflict(exc) from exc
        return self._require(profile_id)

    def names_by_layout(self) -> dict[str, list[str]]:
        with self._sessions() as session:
            pairs = session.execute(
                select(EventProfileLayoutRow.template_key, EventProfileRow)
                .join(EventProfileRow, EventProfileRow.id == EventProfileLayoutRow.profile_id)
                .order_by(EventProfileRow.name)
            )
            usage: dict[str, list[str]] = {}
            for template_key, row in pairs:
                usage.setdefault(template_key, []).append(_usage_name(row))
            return usage

    def _require(self, profile_id: str) -> EventProfile:
        profile = self.get(profile_id)
        if profile is None:  # pragma: no cover - rows are never hard-deleted
            raise ProfileNotFoundError(profile_id)
        return profile

    @staticmethod
    def _explain_miss(session: Session, profile_id: str, expected_revision: int) -> None:
        existing = session.get(EventProfileRow, profile_id)
        if existing is None:
            raise ProfileNotFoundError(profile_id)
        if existing.deleted_at is not None:
            raise ProfileConflictError("the profile is deleted; restore it first")
        raise ProfileConflictError(
            f"the profile was changed elsewhere (revision {existing.revision}, "
            f"expected {expected_revision}); reload and try again"
        )
