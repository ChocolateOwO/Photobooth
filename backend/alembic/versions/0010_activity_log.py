"""Activity log: what happened at the booth and in Admin.

`activity_log` keeps small, privacy-safe records: a type from a fixed list, when, who caused it,
the visit and event it belongs to and a few allowlisted facts (never a token, password, path, IP,
image or free text). A visit's records go with the visit (ON DELETE CASCADE); an event profile
deleted for good leaves its records without a profile (SET NULL).

Nothing that existed before is changed; a downgrade drops the table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_activity_log"
down_revision = "0009_outputs_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("actor", sa.String(16), nullable=False),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("booth_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("event_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("admin_username", sa.String(64), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "actor IN ('booth', 'guest', 'admin', 'system')", name="ck_activity_log_actor"
        ),
    )
    op.create_index("ix_activity_log_at", "activity_log", ["at", "id"])
    op.create_index("ix_activity_log_session", "activity_log", ["session_id", "at"])
    op.create_index("ix_activity_log_type", "activity_log", ["type", "at"])


def downgrade() -> None:
    op.drop_index("ix_activity_log_type", table_name="activity_log")
    op.drop_index("ix_activity_log_session", table_name="activity_log")
    op.drop_index("ix_activity_log_at", table_name="activity_log")
    op.drop_table("activity_log")
