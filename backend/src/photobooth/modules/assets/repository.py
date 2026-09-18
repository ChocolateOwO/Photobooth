"""SQLAlchemy AssetRepository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine, Integer, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from photobooth.core.db import Base, UtcDateTime
from photobooth.modules.assets.domain import AssetKind, AssetRepository, MediaAsset


class MediaAssetRow(Base):
    __tablename__ = "media_assets"
    __table_args__ = (UniqueConstraint("kind", "sha256", name="uq_media_assets_kind_sha256"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)

    def to_domain(self) -> MediaAsset:
        return MediaAsset(
            id=self.id,
            kind=AssetKind(self.kind),
            storage_key=self.storage_key,
            mime=self.mime,
            width=self.width,
            height=self.height,
            bytes=self.bytes,
            sha256=self.sha256,
            created_at=self.created_at,
        )


class SqlAssetRepository(AssetRepository):
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def add(self, asset: MediaAsset) -> MediaAsset:
        row = MediaAssetRow(
            id=asset.id,
            kind=asset.kind.value,
            storage_key=asset.storage_key,
            mime=asset.mime,
            width=asset.width,
            height=asset.height,
            bytes=asset.bytes,
            sha256=asset.sha256,
            created_at=asset.created_at,
        )
        try:
            with self._sessions.begin() as session:
                session.add(row)
        except IntegrityError:
            existing = self.find_by_hash(asset.kind, asset.sha256)
            if existing is None:
                raise
            return existing
        return asset

    def remove(self, asset_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(MediaAssetRow, asset_id)
            if row is not None:
                session.delete(row)

    def get(self, asset_id: str) -> MediaAsset | None:
        with self._sessions() as session:
            row = session.get(MediaAssetRow, asset_id)
            return None if row is None else row.to_domain()

    def find_by_hash(self, kind: AssetKind, sha256: str) -> MediaAsset | None:
        with self._sessions() as session:
            row = _one(session, kind, sha256)
            return None if row is None else row.to_domain()


def _one(session: Session, kind: AssetKind, sha256: str) -> MediaAssetRow | None:
    return session.scalars(
        select(MediaAssetRow).where(
            MediaAssetRow.kind == kind.value, MediaAssetRow.sha256 == sha256
        )
    ).first()
