"""Admin users, logo/background media assets and Event Profiles.

Revision ID: 0002_admin_profiles
Revises: 0001_baseline
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_admin_profiles"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(32), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "media_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False, unique=True),
        sa.Column("mime", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "sha256", name="uq_media_assets_kind_sha256"),
    )
    op.create_table(
        "event_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(80), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("subtitle", sa.String(240), nullable=False),
        sa.Column("start_button_text", sa.String(40), nullable=False),
        sa.Column(
            "logo_asset_id",
            sa.String(36),
            sa.ForeignKey("media_assets.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "background_asset_id",
            sa.String(36),
            sa.ForeignKey("media_assets.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("background_color", sa.String(7), nullable=False),
        sa.Column("primary_color", sa.String(7), nullable=False),
        sa.Column("secondary_color", sa.String(7), nullable=False),
        sa.Column("button_color", sa.String(7), nullable=False),
        sa.Column("text_color", sa.String(7), nullable=False),
        sa.Column("countdown_seconds", sa.Integer(), nullable=False),
        sa.Column("mirror", sa.Boolean(), nullable=False),
        sa.Column("inactivity_timeout_s", sa.Integer(), nullable=False),
        sa.Column("retake_mode", sa.String(16), nullable=False),
        sa.Column("delivery_mode", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("countdown_seconds = 5", name="ck_event_profiles_countdown_fixed"),
        sa.CheckConstraint(
            "inactivity_timeout_s BETWEEN 30 AND 900", name="ck_event_profiles_inactivity_range"
        ),
        sa.CheckConstraint(
            "NOT (is_active = 1 AND deleted_at IS NOT NULL)",
            name="ck_event_profiles_deleted_not_active",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_event_profiles_revision_positive"),
    )
    op.create_index(
        "uq_event_profiles_live_name",
        "event_profiles",
        ["name_key"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_event_profiles_single_active",
        "event_profiles",
        ["is_active"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
    )
    op.create_table(
        "event_profile_layouts",
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("event_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("template_key", sa.String(64), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("event_profile_layouts")
    op.drop_index("uq_event_profiles_single_active", table_name="event_profiles")
    op.drop_index("uq_event_profiles_live_name", table_name="event_profiles")
    op.drop_table("event_profiles")
    op.drop_table("media_assets")
    op.drop_table("admin_users")
