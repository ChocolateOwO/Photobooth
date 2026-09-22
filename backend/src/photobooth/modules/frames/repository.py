"""SQLAlchemy FrameRepository. Frame rows point at immutable media assets."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Engine,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from photobooth.core.db import Base, UtcDateTime
from photobooth.modules.assets.repository import MediaAssetRow
from photobooth.modules.frames.domain import (
    FrameAsset,
    FrameNotFoundError,
    FrameReadOnlyError,
    FrameRepository,
    FrameStatus,
    FrameValidationError,
    FrameValidationReport,
)


class FrameAssetRow(Base):
    __tablename__ = "frame_assets"
    __table_args__ = (
        UniqueConstraint("template_key", "name", name="uq_frame_assets_template_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    media_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    report: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    family: Mapped[str | None] = mapped_column(String(32), nullable=True)


def _report_json(report: FrameValidationReport) -> str:
    return json.dumps(
        {
            "warnings": list(report.warnings),
            "width": report.width,
            "height": report.height,
            "slot_transparency": [round(value, 4) for value in report.slot_transparency],
        }
    )


def _report_of(raw: str) -> FrameValidationReport:
    data = json.loads(raw)
    return FrameValidationReport(
        warnings=tuple(str(w) for w in data.get("warnings", [])),
        width=int(data.get("width", 0)),
        height=int(data.get("height", 0)),
        slot_transparency=tuple(float(v) for v in data.get("slot_transparency", [])),
    )


def _to_domain(row: FrameAssetRow, asset: MediaAssetRow | None) -> FrameAsset:
    return FrameAsset(
        id=row.id,
        media_asset_id=row.media_asset_id,
        template_key=row.template_key,
        template_version=row.template_version,
        name=row.name,
        status=FrameStatus(row.status),
        report=_report_of(row.report),
        created_at=row.created_at,
        updated_at=row.updated_at,
        sha256="" if asset is None else asset.sha256,
        bytes=0 if asset is None else asset.bytes,
        builtin=row.builtin,
        family=row.family,
    )


class SqlFrameRepository(FrameRepository):
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def add(self, frame: FrameAsset) -> FrameAsset:
        row = FrameAssetRow(
            id=frame.id,
            media_asset_id=frame.media_asset_id,
            template_key=frame.template_key,
            template_version=frame.template_version,
            name=frame.name,
            status=frame.status.value,
            report=_report_json(frame.report),
            created_at=frame.created_at,
            updated_at=frame.updated_at,
            builtin=False,  # built-in rows come only from migration 0004
            family=None,
        )
        try:
            with self._sessions.begin() as session:
                session.add(row)
        except IntegrityError as exc:
            raise FrameValidationError(
                [f"A frame called '{frame.name}' already exists for this layout."]
            ) from exc
        return self._require(frame.id)

    def list_frames(self, template_key: str | None = None) -> list[FrameAsset]:
        # Built-in frames first in each layout, then the admin's own frames by name.
        query = select(FrameAssetRow).order_by(
            FrameAssetRow.template_key, FrameAssetRow.builtin.desc(), FrameAssetRow.name
        )
        if template_key is not None:
            query = query.where(FrameAssetRow.template_key == template_key)
        with self._sessions() as session:
            rows = list(session.scalars(query))
            return [_to_domain(row, session.get(MediaAssetRow, row.media_asset_id)) for row in rows]

    def get(self, frame_id: str) -> FrameAsset | None:
        with self._sessions() as session:
            row = session.get(FrameAssetRow, frame_id)
            if row is None:
                return None
            return _to_domain(row, session.get(MediaAssetRow, row.media_asset_id))

    def replace_file(
        self, frame_id: str, media_asset_id: str, report: FrameValidationReport, at: datetime
    ) -> FrameAsset:
        with self._sessions.begin() as session:
            row = session.get(FrameAssetRow, frame_id)
            if row is None:
                raise FrameNotFoundError(frame_id)
            if row.builtin:
                raise FrameReadOnlyError()
            row.media_asset_id = media_asset_id  # the previous asset row stays (immutable)
            row.report = _report_json(report)
            row.updated_at = at
        return self._require(frame_id)

    def rename(self, frame_id: str, name: str, at: datetime) -> FrameAsset:
        try:
            with self._sessions.begin() as session:
                row = session.get(FrameAssetRow, frame_id)
                if row is None:
                    raise FrameNotFoundError(frame_id)
                if row.builtin:
                    raise FrameReadOnlyError()
                row.name = name
                row.updated_at = at
        except IntegrityError as exc:
            raise FrameValidationError(
                [f"A frame called '{name}' already exists for this layout."]
            ) from exc
        return self._require(frame_id)

    def delete(self, frame_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(FrameAssetRow, frame_id)
            if row is None:
                raise FrameNotFoundError(frame_id)
            if row.builtin:
                raise FrameReadOnlyError()
            session.delete(row)

    def uses_asset(self, asset_id: str, ignore_frame_id: str | None = None) -> bool:
        query = select(FrameAssetRow.id).where(FrameAssetRow.media_asset_id == asset_id)
        if ignore_frame_id is not None:
            query = query.where(FrameAssetRow.id != ignore_frame_id)
        with self._sessions() as session:
            return session.scalars(query).first() is not None

    def _require(self, frame_id: str) -> FrameAsset:
        frame = self.get(frame_id)
        if frame is None:  # pragma: no cover - the row was just written
            raise FrameNotFoundError(frame_id)
        return frame
