"""Booth visits know whether they are an organizer's test.

The Admin "Test booth" page runs the real booth screens against a saved profile with the real
camera. Those visits and their photos must never be mistaken for a guest's: they are marked here,
they are cleaned up when the organizer leaves the test, and stale ones are swept at start-up.
A real booth visit is never touched by that cleanup.

SQLite can add the column in place; existing visits are guests' (0), which is what the column
defaults to.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_test_sessions"
down_revision = "0007_booth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "booth_sessions",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_booth_sessions_test",
        "booth_sessions",
        ["is_test"],
        sqlite_where=sa.text("is_test = 1"),
    )


def downgrade() -> None:
    # The organizer's test visits are removed with the column: they are scratch data by design.
    op.execute(sa.text("DELETE FROM booth_sessions WHERE is_test = 1"))
    op.drop_index("ix_booth_sessions_test", table_name="booth_sessions")
    op.drop_column("booth_sessions", "is_test")
