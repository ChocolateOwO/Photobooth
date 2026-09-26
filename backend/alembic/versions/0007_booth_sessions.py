"""Booth sessions and their captures (Phase 6 + 7).

A visit to the booth becomes a row: the event's settings are copied into it once (so an organizer
editing the profile mid-visit changes nothing for the guest already taking photos), the confirmed
frame is pinned when the guest chooses it, and every photo is one `capture_assets` row.

The database keeps the rules that matter, not only the service:
- one unfinished session per device (partial unique index);
- one photo that counts per shot (partial unique index where status = 'ok');
- one row per attempt of a shot, and one row per idempotency key, so a repeated request can never
  make a second photo;
- a session never counts more photos than it expects.

Nothing here is deleted by this migration; downgrade drops the three new tables (and with them the
rows describing visits, never the frames, media or profiles).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_booth_sessions"
down_revision = "0006_photo_sizes_countdown"
branch_labels = None
depends_on = None

_OPEN = "state NOT IN ('completed', 'cancelled', 'error', 'abandoned')"


def upgrade() -> None:
    op.create_table(
        "booth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column(
            "event_profile_id",
            sa.String(36),
            sa.ForeignKey("event_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("profile_snapshot", sa.Text(), nullable=False),
        sa.Column("selection_snapshot", sa.Text(), nullable=True),
        sa.Column("expected_capture_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_capture_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_capture_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligibility_result", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "successful_capture_count <= expected_capture_count",
            name="ck_booth_sessions_capture_count",
        ),
        sa.CheckConstraint("state_version >= 1", name="ck_booth_sessions_state_version"),
    )
    op.create_index(
        "uq_booth_sessions_open_device",
        "booth_sessions",
        ["device_id"],
        unique=True,
        sqlite_where=sa.text(_OPEN),
    )
    op.create_index("ix_booth_sessions_state", "booth_sessions", ["state"])

    op.create_table(
        "capture_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("booth_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("shot_index", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("mirrored", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_reason", sa.String(64), nullable=True),
        sa.Column("file_delete_pending", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("file_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "session_id", "shot_index", "attempt_no", name="uq_capture_assets_attempt"
        ),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_capture_assets_key"),
        sa.CheckConstraint("shot_index >= 1", name="ck_capture_assets_shot"),
        sa.CheckConstraint("attempt_no >= 1", name="ck_capture_assets_attempt"),
    )
    op.create_index(
        "uq_capture_assets_shot_ok",
        "capture_assets",
        ["session_id", "shot_index"],
        unique=True,
        sqlite_where=sa.text("status = 'ok'"),
    )
    op.create_index(
        "ix_capture_assets_delete_pending",
        "capture_assets",
        ["file_delete_pending"],
        sqlite_where=sa.text("file_delete_pending = 1"),
    )

    op.create_table(
        "booth_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("booth_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("owner_boot_id", sa.String(32), nullable=False),
        sa.Column("result_ref", sa.String(36), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_booth_operations_key"),
    )
    op.create_index(
        "ix_booth_operations_pending",
        "booth_operations",
        ["status"],
        sqlite_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "booth_device_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result_ref", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("device_id", "idempotency_key", name="uq_device_operations_key"),
    )


def downgrade() -> None:
    op.drop_table("booth_device_operations")
    op.drop_index("ix_booth_operations_pending", table_name="booth_operations")
    op.drop_table("booth_operations")
    op.drop_index("ix_capture_assets_delete_pending", table_name="capture_assets")
    op.drop_index("uq_capture_assets_shot_ok", table_name="capture_assets")
    op.drop_table("capture_assets")
    op.drop_index("ix_booth_sessions_state", table_name="booth_sessions")
    op.drop_index("uq_booth_sessions_open_device", table_name="booth_sessions")
    op.drop_table("booth_sessions")
