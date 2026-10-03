"""Retention policies are selected per Event Profile, and each visit keeps its own deadlines.

- `retention_policies`: named policies (photos, finished photos, take-home link, visit records).
  The booth's single policy of 0011 becomes the policy "Standard", the default for new events.
- `retention_housekeeping`: one row with what belongs to the whole booth (temporary files,
  activity log, backups, application logs), carried over from 0011 with its revision.
- `event_profiles.retention_policy_id`: every existing profile, deleted ones included, selects
  "Standard".
- `booth_sessions.retention`: the policy values a visit froze when it started (JSON). Every
  existing visit gets the values "Standard" has now, so no deadline changes with this migration.

Columns are added in place: `event_profiles` and `booth_sessions` are parents of other tables and
are never rebuilt here (with foreign keys on, rebuilding a parent would cascade into its
children). The 0011 table has no foreign keys and is simply replaced. The selected policy is
checked by the application (a policy an Event Profile uses can not be deleted).

Downgrade: the default policy and the housekeeping row become the single 0011 policy again; other
policies and every visit's frozen values are dropped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0012_policy_per_event"
down_revision = "0011_retention"
branch_labels = None
depends_on = None

STANDARD_POLICY_ID = "00000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    conn = op.get_bind()
    old = (
        conn.execute(
            sa.text(
                "SELECT originals_days, outputs_days, link_days, temp_hours, metadata_mode, "
                "metadata_days, activity_log_days, backup_days, app_log_days, revision, updated_at "
                "FROM retention_policy WHERE id = 1"
            )
        )
        .mappings()
        .first()
    )
    defaults = {
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
    current = {**defaults, **(dict(old) if old else {})}
    now = datetime.now(UTC)

    policies = op.create_table(
        "retention_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("name_key", sa.String(60), nullable=False),
        sa.Column("originals_days", sa.Integer(), nullable=False),
        sa.Column("outputs_days", sa.Integer(), nullable=False),
        sa.Column("link_days", sa.Integer(), nullable=False),
        sa.Column("metadata_mode", sa.String(16), nullable=False),
        sa.Column("metadata_days", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "metadata_mode IN ('keep', 'anonymize', 'delete')", name="ck_retention_policies_mode"
        ),
    )
    op.create_index("uq_retention_policies_name", "retention_policies", ["name_key"], unique=True)
    op.create_index(
        "uq_retention_policies_default",
        "retention_policies",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
    )
    op.bulk_insert(
        policies,
        [
            {
                "id": STANDARD_POLICY_ID,
                "name": "Standard",
                "name_key": "standard",
                "originals_days": current["originals_days"],
                "outputs_days": current["outputs_days"],
                "link_days": current["link_days"],
                "metadata_mode": current["metadata_mode"],
                "metadata_days": current["metadata_days"],
                "is_default": True,
                "revision": 1,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    housekeeping = op.create_table(
        "retention_housekeeping",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("temp_hours", sa.Integer(), nullable=False),
        sa.Column("activity_log_days", sa.Integer(), nullable=False),
        sa.Column("backup_days", sa.Integer(), nullable=False),
        sa.Column("app_log_days", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_retention_housekeeping_single"),
    )
    op.bulk_insert(
        housekeeping,
        [
            {
                "id": 1,
                "temp_hours": current["temp_hours"],
                "activity_log_days": current["activity_log_days"],
                "backup_days": current["backup_days"],
                "app_log_days": current["app_log_days"],
                # A dry run made before the upgrade can not confirm a deletion after it.
                "revision": int(current["revision"]) + 1,
                "updated_at": now,
            }
        ],
    )
    op.drop_table("retention_policy")

    op.add_column(
        "event_profiles",
        sa.Column("retention_policy_id", sa.String(36), nullable=False, server_default=""),
    )
    conn.execute(
        sa.text("UPDATE event_profiles SET retention_policy_id = :policy"),
        {"policy": STANDARD_POLICY_ID},
    )

    frozen = json.dumps(
        {
            "policy_id": STANDARD_POLICY_ID,
            "policy_name": "Standard",
            "originals_days": current["originals_days"],
            "outputs_days": current["outputs_days"],
            "link_days": current["link_days"],
            "records_mode": current["metadata_mode"],
            "records_days": current["metadata_days"],
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    op.add_column(
        "booth_sessions",
        sa.Column("retention", sa.Text(), nullable=False, server_default=""),
    )
    conn.execute(sa.text("UPDATE booth_sessions SET retention = :frozen"), {"frozen": frozen})


def downgrade() -> None:
    conn = op.get_bind()
    policy = (
        conn.execute(
            sa.text(
                "SELECT originals_days, outputs_days, link_days, metadata_mode, metadata_days "
                "FROM retention_policies WHERE is_default = 1"
            )
        )
        .mappings()
        .first()
    )
    house = (
        conn.execute(
            sa.text(
                "SELECT temp_hours, activity_log_days, backup_days, app_log_days, revision "
                "FROM retention_housekeeping WHERE id = 1"
            )
        )
        .mappings()
        .first()
    )

    op.drop_column("booth_sessions", "retention")
    op.drop_column("event_profiles", "retention_policy_id")

    single = op.create_table(
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
    p = dict(policy) if policy else {}
    h = dict(house) if house else {}
    op.bulk_insert(
        single,
        [
            {
                "id": 1,
                "originals_days": p.get("originals_days", 7),
                "outputs_days": p.get("outputs_days", 30),
                "link_days": p.get("link_days", 7),
                "temp_hours": h.get("temp_hours", 24),
                "metadata_mode": p.get("metadata_mode", "keep"),
                "metadata_days": p.get("metadata_days", 90),
                "activity_log_days": h.get("activity_log_days", 90),
                "backup_days": h.get("backup_days", 7),
                "app_log_days": h.get("app_log_days", 14),
                "revision": int(h.get("revision", 1)) + 1,
                "updated_at": datetime.now(UTC),
            }
        ],
    )
    op.drop_table("retention_housekeeping")
    op.drop_index("uq_retention_policies_default", table_name="retention_policies")
    op.drop_index("uq_retention_policies_name", table_name="retention_policies")
    op.drop_table("retention_policies")
