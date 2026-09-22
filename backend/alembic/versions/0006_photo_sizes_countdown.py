"""Profiles choose photo sizes (not single frames); the countdown becomes 1-10 seconds.

Photo sizes: `event_profile_layouts` (profile, layout key, position) becomes the authoritative
list of what a profile offers. Every valid frame of an enabled size is shown to participants, so
frames uploaded, renamed, replaced or deleted later need no profile edit. The per-frame list of
0005 (`event_profile_available_frames`) is dropped: it is no longer a product rule, and its
FK RESTRICT would keep blocking the deletion of uploaded frames. Frame rows and their stored
files are not touched.

Upgrade, per profile (deleted and active ones too): the enabled sizes are the layouts of the
frames it offered, sorted by layout key (the template catalogue order the app uses). A profile
that offered no frame gets no size (as before, it can not be activated until one is chosen).

Countdown: the CHECK constraint `countdown_seconds = 5` becomes `countdown_seconds BETWEEN 1 AND
10`. SQLite can not alter a CHECK constraint, so `event_profiles` is rebuilt from its own stored
CREATE statement (same columns, foreign keys and indexes, only that constraint changed). Existing
values stay 5. The rebuild happens while no other table references `event_profiles` (the old
per-frame table is already dropped, the new size table is created afterwards), so no ON DELETE
action can fire while the old table is dropped.

Downgrade: every countdown returns to 5 (the old rule), the constraint is restored, and each
profile's per-frame list is rebuilt from its sizes: every valid frame of those sizes, built-in
frames first, then by name.

Revision ID: 0006_photo_sizes_countdown
Revises: 0005_available_frames
Create Date: 2026-09-22
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_photo_sizes_countdown"
down_revision: str | None = "0005_available_frames"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIXED = "CONSTRAINT ck_event_profiles_countdown_fixed CHECK (countdown_seconds = 5)"
RANGE = "CONSTRAINT ck_event_profiles_countdown_range CHECK (countdown_seconds BETWEEN 1 AND 10)"


def _rebuild_profiles(conn: sa.Connection, old: str, new: str) -> None:
    """Recreate event_profiles with one CHECK constraint replaced; everything else identical."""
    create = conn.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'event_profiles'")
    ).scalar_one()
    if old not in create:
        raise RuntimeError(f"event_profiles does not have the expected constraint: {old}")
    indexes = (
        conn.execute(
            sa.text(
                "SELECT sql FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = 'event_profiles' AND sql IS NOT NULL"
            )
        )
        .scalars()
        .all()
    )
    renamed, count = re.subn(
        r'CREATE TABLE\s+"?event_profiles"?', "CREATE TABLE _event_profiles_new", create, count=1
    )
    if count != 1:
        raise RuntimeError("could not read the event_profiles table definition")
    conn.execute(sa.text(renamed.replace(old, new, 1)))
    conn.execute(sa.text("INSERT INTO _event_profiles_new SELECT * FROM event_profiles"))
    conn.execute(sa.text("DROP TABLE event_profiles"))
    conn.execute(sa.text("ALTER TABLE _event_profiles_new RENAME TO event_profiles"))
    for index_sql in indexes:
        conn.execute(sa.text(index_sql))


def upgrade() -> None:
    conn = op.get_bind()
    sizes: dict[str, list[str]] = {}
    for profile_id, template_key in conn.execute(
        sa.text(
            "SELECT DISTINCT a.profile_id, f.template_key FROM event_profile_available_frames a "
            "JOIN frame_assets f ON f.id = a.frame_id ORDER BY a.profile_id, f.template_key"
        )
    ).fetchall():
        sizes.setdefault(profile_id, []).append(template_key)

    op.drop_table("event_profile_available_frames")
    _rebuild_profiles(conn, FIXED, RANGE)

    op.create_table(
        "event_profile_layouts",
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("event_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("template_key", sa.String(64), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("profile_id", "position", name="uq_event_profile_layout_position"),
        sa.CheckConstraint("position >= 0", name="ck_event_profile_layout_position"),
    )
    for profile_id, keys in sizes.items():
        for position, template_key in enumerate(keys):
            conn.execute(
                sa.text(
                    "INSERT INTO event_profile_layouts (profile_id, template_key, position) "
                    "VALUES (:profile, :key, :position)"
                ),
                {"profile": profile_id, "key": template_key, "position": position},
            )


def downgrade() -> None:
    conn = op.get_bind()
    sizes: dict[str, list[str]] = {}
    for profile_id, template_key in conn.execute(
        sa.text(
            "SELECT profile_id, template_key FROM event_profile_layouts "
            "ORDER BY profile_id, position"
        )
    ).fetchall():
        sizes.setdefault(profile_id, []).append(template_key)

    op.drop_table("event_profile_layouts")
    conn.execute(sa.text("UPDATE event_profiles SET countdown_seconds = 5"))
    _rebuild_profiles(conn, RANGE, FIXED)

    op.create_table(
        "event_profile_available_frames",
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("event_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "frame_id",
            sa.String(36),
            sa.ForeignKey("frame_assets.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("profile_id", "position", name="uq_event_profile_frame_position"),
        sa.CheckConstraint("position >= 0", name="ck_event_profile_frame_position"),
    )
    for profile_id, keys in sizes.items():
        position = 0
        for template_key in keys:
            frames = conn.execute(
                sa.text(
                    "SELECT id FROM frame_assets WHERE template_key = :key AND status = 'valid' "
                    "ORDER BY builtin DESC, name"
                ),
                {"key": template_key},
            ).scalars()
            for frame_id in frames:
                conn.execute(
                    sa.text(
                        "INSERT INTO event_profile_available_frames "
                        "(profile_id, frame_id, position) VALUES (:profile, :frame, :position)"
                    ),
                    {"profile": profile_id, "frame": frame_id, "position": position},
                )
                position += 1
