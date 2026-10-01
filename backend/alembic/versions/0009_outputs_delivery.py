"""Finished photos and the guests' take-home links.

`output_assets` records each finished photo of a visit (a print, or one strip of a 2x6) with
exactly what it was made from, so the same inputs are never rendered twice and the database
itself allows only one counted photo per output. `delivery_tokens` holds the take-home links:
only the SHA-256 of a token is stored, and a visit has at most one link that is not revoked.

Nothing that existed before is changed. Visits keep their states; the new state `delivered`
only appears from here on, and a downgrade turns those visits into `completed` (their photos
were made; the tables that described them go with the downgrade).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_outputs_delivery"
down_revision = "0008_test_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "output_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("booth_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("output_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("render_fingerprint", sa.String(64), nullable=False),
        sa.Column("template_key", sa.String(64), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("frame_id", sa.String(36), nullable=False),
        sa.Column("frame_sha256", sa.String(64), nullable=False),
        sa.Column("capture_ids", sa.Text(), nullable=False),
        sa.Column("decoration", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.String(255), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_reason", sa.String(64), nullable=True),
        sa.Column("file_delete_pending", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("file_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("output_index >= 1", name="ck_output_assets_index"),
    )
    op.create_index(
        "uq_output_assets_index_ok",
        "output_assets",
        ["session_id", "output_index"],
        unique=True,
        sqlite_where=sa.text("status = 'ok'"),
    )
    op.create_index("ix_output_assets_session", "output_assets", ["session_id"])
    op.create_index("ix_output_assets_operation", "output_assets", ["operation_id"])
    op.create_index(
        "ix_output_assets_delete_pending",
        "output_assets",
        ["file_delete_pending"],
        sqlite_where=sa.text("file_delete_pending = 1"),
    )

    op.create_table(
        "delivery_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("booth_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("uq_delivery_tokens_hash", "delivery_tokens", ["token_hash"], unique=True)
    op.create_index(
        "uq_delivery_tokens_live",
        "delivery_tokens",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    # A delivered visit had its photos made: it ends as completed, not abandoned.
    op.execute(sa.text("UPDATE booth_sessions SET state = 'completed' WHERE state = 'delivered'"))
    # Render operations describe rows that no longer exist after this downgrade.
    op.execute(sa.text("DELETE FROM booth_operations WHERE kind = 'render'"))
    op.drop_index("uq_delivery_tokens_live", table_name="delivery_tokens")
    op.drop_index("uq_delivery_tokens_hash", table_name="delivery_tokens")
    op.drop_table("delivery_tokens")
    op.drop_index("ix_output_assets_delete_pending", table_name="output_assets")
    op.drop_index("ix_output_assets_operation", table_name="output_assets")
    op.drop_index("ix_output_assets_session", table_name="output_assets")
    op.drop_index("uq_output_assets_index_ok", table_name="output_assets")
    op.drop_table("output_assets")
