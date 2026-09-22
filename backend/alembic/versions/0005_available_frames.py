"""Participants choose the frame: profiles offer an ordered list of available frames.

Replaces "one selected frame per enabled layout" (event_profile_frames) and the separate layout
list (event_profile_layouts) with one ordered many-to-many list, event_profile_available_frames.
A layout is offered exactly when at least one available frame uses it.

Upgrade, per profile (deleted and active ones too), in the profile's previous layout order:
- the frame previously selected for a layout becomes an available frame;
- an enabled layout that had no frame gets its built-in default (Midnight for dark themes, Minimal
  Light for light ones), so every previously enabled layout stays offered;
- no uploaded frame is added that the profile did not already use;
- a profile that would end up with no frame at all (never expected) gets the built-in frames of
  its family for every layout, so an active profile always keeps at least one valid frame.
Every other profile setting is left untouched. `allow_surprise_me` is added (off).

Downgrade rebuilds the layout list (in first-use order) and one frame per layout (the first).

Revision ID: 0005_available_frames
Revises: 0004_builtin_frames_themes
Create Date: 2026-09-21
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from photobooth.modules.frames.builtin import LAYOUTS, builtin_frame_id
from photobooth.modules.themes.domain import is_dark

revision: str = "0005_available_frames"
down_revision: str | None = "0004_builtin_frames_themes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _family(theme_json: str) -> str:
    tokens = json.loads(theme_json).get("tokens", {})
    return "midnight" if tokens and is_dark(tokens) else "minimal_light"


def _existing(conn: sa.Connection, frame_id: str) -> bool:
    return (
        conn.execute(
            sa.text("SELECT 1 FROM frame_assets WHERE id = :id"), {"id": frame_id}
        ).scalar()
        is not None
    )


def upgrade() -> None:
    conn = op.get_bind()
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
    op.add_column(
        "event_profiles",
        sa.Column("allow_surprise_me", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    profiles = conn.execute(sa.text("SELECT id, theme FROM event_profiles ORDER BY id")).fetchall()
    for profile_id, theme_json in profiles:
        family = _family(theme_json)
        layouts = conn.execute(
            sa.text(
                "SELECT template_key FROM event_profile_layouts WHERE profile_id = :id "
                "ORDER BY sort_order"
            ),
            {"id": profile_id},
        ).scalars()
        selected = dict(
            conn.execute(
                sa.text(
                    "SELECT template_key, frame_id FROM event_profile_frames WHERE profile_id = :id"
                ),
                {"id": profile_id},
            ).fetchall()
        )
        frames: list[str] = []
        for layout in layouts:
            frame_id = selected.get(layout)
            if frame_id is None and layout in LAYOUTS:
                frame_id = builtin_frame_id(family, layout)
            if frame_id is not None and frame_id not in frames and _existing(conn, frame_id):
                frames.append(frame_id)
        if not frames:
            frames = [builtin_frame_id(family, layout) for layout in LAYOUTS]
            frames = [frame_id for frame_id in frames if _existing(conn, frame_id)]
        for position, frame_id in enumerate(frames):
            conn.execute(
                sa.text(
                    "INSERT INTO event_profile_available_frames (profile_id, frame_id, position) "
                    "VALUES (:profile, :frame, :position)"
                ),
                {"profile": profile_id, "frame": frame_id, "position": position},
            )

    op.drop_table("event_profile_frames")
    op.drop_table("event_profile_layouts")


def downgrade() -> None:
    conn = op.get_bind()
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
    for (profile_id,) in conn.execute(sa.text("SELECT id FROM event_profiles")).fetchall():
        rows = conn.execute(
            sa.text(
                "SELECT a.frame_id, f.template_key FROM event_profile_available_frames a "
                "JOIN frame_assets f ON f.id = a.frame_id WHERE a.profile_id = :id "
                "ORDER BY a.position"
            ),
            {"id": profile_id},
        ).fetchall()
        first: dict[str, str] = {}
        for frame_id, template_key in rows:
            first.setdefault(template_key, frame_id)
        layouts = list(first) or ["strip_2x6"]  # the old model needed at least one layout
        for index, template_key in enumerate(layouts):
            conn.execute(
                sa.text(
                    "INSERT INTO event_profile_layouts (profile_id, template_key, sort_order) "
                    "VALUES (:id, :key, :order)"
                ),
                {"id": profile_id, "key": template_key, "order": index},
            )
        for template_key, frame_id in first.items():
            conn.execute(
                sa.text(
                    "INSERT INTO event_profile_frames (profile_id, template_key, frame_id) "
                    "VALUES (:id, :key, :frame)"
                ),
                {"id": profile_id, "key": template_key, "frame": frame_id},
            )
    op.execute("ALTER TABLE event_profiles DROP COLUMN allow_surprise_me")
    op.drop_table("event_profile_available_frames")
