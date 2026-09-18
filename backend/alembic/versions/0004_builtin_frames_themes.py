"""Built-in frames, complete event themes, and built-in default frames for existing profiles.

- frame_assets gains `builtin` and `family`; the packaged built-in frames (every family for every
  layout) are inserted with fixed ids. Their media rows point at content-addressed storage keys;
  the files themselves are written through the StorageProvider when the app starts.
- event_profiles: the five pre-theme colours become one complete, accessible `theme` (JSON).
- Every enabled layout of every existing profile that has no frame gets a built-in default
  (Midnight for dark themes, Minimal Light for light ones). Nothing else in a profile changes.

Revision ID: 0004_builtin_frames_themes
Revises: 0003_frames
Create Date: 2026-09-18
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from photobooth.modules.frames.builtin import (
    BUILTIN_NAMESPACE,
    BUILTIN_TEMPLATE_VERSION,
    builtin_frame_id,
    builtin_frames,
)
from photobooth.modules.frames.validator import PillowFrameValidator
from photobooth.modules.templates.repository import JsonTemplateRepository
from photobooth.modules.themes.domain import (
    is_dark,
    luminance,
    theme_from_legacy,
    to_rgb,
)

revision: str = "0004_builtin_frames_themes"
down_revision: str | None = "0003_frames"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_COLUMNS = (
    "background_color",
    "primary_color",
    "secondary_color",
    "button_color",
    "text_color",
)


def _media_id(family: str, template_key: str) -> str:
    return str(uuid.uuid5(BUILTIN_NAMESPACE, f"media/{family}/{template_key}"))


def _insert_builtin_frames(conn: sa.Connection, now: datetime) -> None:
    templates = {
        t.key: t for t in JsonTemplateRepository().all() if t.version == BUILTIN_TEMPLATE_VERSION
    }
    validator = PillowFrameValidator()
    for frame in builtin_frames():
        data = frame.read()
        report = validator.validate(data, templates[frame.template_key])  # never insert a bad frame
        sha = hashlib.sha256(data).hexdigest()
        existing = conn.execute(
            sa.text("SELECT id FROM media_assets WHERE kind = 'frame' AND sha256 = :sha"),
            {"sha": sha},
        ).scalar()
        media_id = existing or _media_id(frame.family.id, frame.template_key)
        if existing is None:
            conn.execute(
                sa.text(
                    "INSERT INTO media_assets (id, kind, storage_key, mime, width, height, bytes, "
                    "sha256, created_at) VALUES (:id, 'frame', :key, 'image/png', :w, :h, :b, "
                    ":sha, "
                    ":at)"
                ),
                {
                    "id": media_id,
                    "key": f"assets/frame/{sha[:2]}/{sha}.png",
                    "w": report.width,
                    "h": report.height,
                    "b": len(data),
                    "sha": sha,
                    "at": now,
                },
            )
        # An uploaded frame that already uses a built-in name keeps working under a clear new name.
        conn.execute(
            sa.text(
                "UPDATE frame_assets SET name = substr(name, 1, 68) || ' (uploaded)' "
                "WHERE template_key = :key AND name = :name AND builtin = 0"
            ),
            {"key": frame.template_key, "name": frame.name},
        )
        conn.execute(
            sa.text(
                "INSERT INTO frame_assets (id, media_asset_id, template_key, template_version, "
                "name, status, report, created_at, updated_at, builtin, family) VALUES (:id, "
                ":media, :key, "
                ":version, :name, 'valid', :report, :at, :at, 1, :family)"
            ),
            {
                "id": frame.id,
                "media": media_id,
                "key": frame.template_key,
                "version": BUILTIN_TEMPLATE_VERSION,
                "name": frame.name,
                "report": json.dumps(
                    {
                        "warnings": list(report.warnings),
                        "width": report.width,
                        "height": report.height,
                        "slot_transparency": [round(v, 4) for v in report.slot_transparency],
                    }
                ),
                "at": now,
                "family": frame.family.id,
            },
        )


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)
    op.add_column(
        "frame_assets",
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("frame_assets", sa.Column("family", sa.String(32), nullable=True))
    _insert_builtin_frames(conn, now)

    op.add_column(
        "event_profiles", sa.Column("theme", sa.Text(), nullable=False, server_default="{}")
    )
    profiles = conn.execute(
        sa.text(f"SELECT id, {', '.join(LEGACY_COLUMNS)} FROM event_profiles")  # noqa: S608 - fixed names
    ).fetchall()
    for row in profiles:
        profile_id, background, primary, secondary, button, _text = row
        theme = theme_from_legacy(
            background.upper(), primary.upper(), secondary.upper(), button.upper()
        )
        conn.execute(
            sa.text("UPDATE event_profiles SET theme = :theme WHERE id = :id"),
            {
                "id": profile_id,
                "theme": json.dumps(
                    {
                        "tokens": dict(theme.tokens),
                        "source": theme.source.value,
                        "preset": theme.preset,
                        "palette": list(theme.palette),
                    },
                    sort_keys=True,
                ),
            },
        )
        family = "midnight" if is_dark(theme.tokens) else "minimal_light"
        missing = conn.execute(
            sa.text(
                "SELECT l.template_key FROM event_profile_layouts l WHERE l.profile_id = :id AND "
                "NOT EXISTS (SELECT 1 FROM event_profile_frames f "
                "WHERE f.profile_id = l.profile_id "
                "AND f.template_key = l.template_key)"
            ),
            {"id": profile_id},
        ).scalars()
        for template_key in missing:
            if template_key not in {"strip_2x6", "print_3x4", "print_4x6"}:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO event_profile_frames (profile_id, template_key, frame_id) "
                    "VALUES (:id, :key, :frame)"
                ),
                {
                    "id": profile_id,
                    "key": template_key,
                    "frame": builtin_frame_id(family, template_key),
                },
            )
    for column in LEGACY_COLUMNS:
        op.execute(f"ALTER TABLE event_profiles DROP COLUMN {column}")


def downgrade() -> None:
    conn = op.get_bind()
    defaults = {
        "background_color": "#101418",
        "primary_color": "#2F6FD6",
        "secondary_color": "#FFB020",
        "button_color": "#2F6FD6",
        "text_color": "#F4F6F8",
    }
    for column, default in defaults.items():
        op.add_column(
            "event_profiles",
            sa.Column(column, sa.String(7), nullable=False, server_default=default),
        )
    for profile_id, raw in conn.execute(sa.text("SELECT id, theme FROM event_profiles")).fetchall():
        tokens = json.loads(raw).get("tokens", {})
        if not tokens:
            continue
        text = tokens["heading"]
        if luminance(to_rgb(text)) < 0.5 and luminance(to_rgb(tokens["background"])) < 0.5:
            text = "#F4F6F8"
        conn.execute(
            sa.text(
                "UPDATE event_profiles SET background_color = :bg, primary_color = :primary, "
                "secondary_color = :secondary, button_color = :button, text_color = :text "
                "WHERE id = :id"
            ),
            {
                "id": profile_id,
                "bg": tokens["background"],
                "primary": tokens["primary_bg"],
                "secondary": tokens["secondary_bg"],
                "button": tokens["primary_bg"],
                "text": text,
            },
        )
    op.execute("ALTER TABLE event_profiles DROP COLUMN theme")

    # Built-in frames did not exist before this revision: drop their selections and rows. Their
    # stored files stay in storage (content-addressed, harmless) and are rewritten on re-upgrade.
    builtin_ids = [
        row[0] for row in conn.execute(sa.text("SELECT id FROM frame_assets WHERE builtin = 1"))
    ]
    media_ids = [
        row[0]
        for row in conn.execute(
            sa.text("SELECT media_asset_id FROM frame_assets WHERE builtin = 1")
        )
    ]
    for frame_id in builtin_ids:
        conn.execute(
            sa.text("DELETE FROM event_profile_frames WHERE frame_id = :id"), {"id": frame_id}
        )
        conn.execute(sa.text("DELETE FROM frame_assets WHERE id = :id"), {"id": frame_id})
    for media_id in media_ids:
        conn.execute(
            sa.text(
                "DELETE FROM media_assets WHERE id = :id AND NOT EXISTS "
                "(SELECT 1 FROM frame_assets WHERE media_asset_id = :id)"
            ),
            {"id": media_id},
        )
    op.execute("ALTER TABLE frame_assets DROP COLUMN family")
    op.execute("ALTER TABLE frame_assets DROP COLUMN builtin")
