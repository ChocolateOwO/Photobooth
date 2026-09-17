"""Frame assets and per-layout frame selection in Event Profiles.

Revision ID: 0003_frames
Revises: 0002_admin_profiles
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_frames"
down_revision: str | None = "0002_admin_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "frame_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "media_asset_id",
            sa.String(36),
            sa.ForeignKey("media_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("template_key", sa.String(64), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("template_key", "name", name="uq_frame_assets_template_name"),
    )
    op.create_table(
        "event_profile_frames",
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("event_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("template_key", sa.String(64), primary_key=True),
        sa.Column(
            "frame_id",
            sa.String(36),
            sa.ForeignKey("frame_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("event_profile_frames")
    op.drop_table("frame_assets")
