"""Retention: the booth's retention policy and the record of its cleanups.

`retention_policy` holds exactly one row (the booth's policy), seeded with the PROVISIONAL plan
defaults: original photos 7 days, finished photos 30 days, take-home link 7 days, temporary files
24 hours, visit records kept; activity log 90 days, backups 7 days, application logs 14 days.
`retention_runs` records every cleanup (dry run or not): when, how it was started, what it counted
or deleted per category, and which categories failed. No path or file name is ever stored.

Nothing that existed before is changed; a downgrade drops both tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_retention"
down_revision = "0010_activity_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    policy = op.create_table(
        "retention_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("originals_days", sa.Integer(), nullable=False),
        sa.Column("outputs_days", sa.Integer(), nullable=False),
        sa.Column("link_days", sa.Integer(), nullable=False),
        sa.Column("temp_hours", sa.Integer(), nullable=False),
        sa.Column("metadata_mode", sa.String(16), nullable=False),
        sa.Column("metadata_days", sa.Integer(), nullable=False),
        sa.Column("activity_log_days", sa.Integer(), nullable=False),
        sa.Column("backup_days", sa.Integer(), nullable=False),
        sa.Column("app_log_days", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_retention_policy_single"),
        sa.CheckConstraint(
            "metadata_mode IN ('keep', 'anonymize', 'delete')", name="ck_retention_policy_mode"
        ),
    )
    op.bulk_insert(
        policy,
        [
            {
                "id": 1,
                "originals_days": 7,
                "outputs_days": 30,
                "link_days": 7,
                "temp_hours": 24,
                "metadata_mode": "keep",
                "metadata_days": 90,
                "activity_log_days": 90,
                "backup_days": 7,
                "app_log_days": 14,
                "revision": 1,
                "updated_at": None,
            }
        ],
    )
    op.create_table(
        "retention_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("counts", sa.Text(), nullable=False),
        sa.Column("errors", sa.Text(), nullable=False),
    )
    op.create_index("ix_retention_runs_started_at", "retention_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_retention_runs_started_at", table_name="retention_runs")
    op.drop_table("retention_runs")
    op.drop_table("retention_policy")
