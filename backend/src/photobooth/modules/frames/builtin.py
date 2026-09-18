"""Built-in frame library: finished transparent PNGs packaged with the app (read-only).

The PNGs live in `photobooth/frames_data/builtin/<family>.<layout>.png`. They were drawn offline by
`scripts/assets/make_builtin_frames.py` (never by an in-browser editor) and are checked against the
Phase 2 template rules by the same validator as uploaded frames. Their ids are fixed, so every
installation and every migration refers to the same rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

BUILTIN_DIRECTORY = Path(__file__).resolve().parents[2] / "frames_data" / "builtin"
BUILTIN_NAMESPACE = uuid.UUID("6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5")
BUILTIN_TEMPLATE_VERSION = 1
LAYOUTS = ("strip_2x6", "print_3x4", "print_4x6")


@dataclass(frozen=True)
class BuiltinFamily:
    id: str
    name: str
    description: str


FAMILIES: tuple[BuiltinFamily, ...] = (
    BuiltinFamily("minimal_light", "Minimal Light", "Warm white paper with fine grey lines."),
    BuiltinFamily("midnight", "Midnight", "Deep blue night sky with stars and a crescent moon."),
    BuiltinFamily(
        "celebration_gold", "Celebration Gold", "Dark espresso with gold borders and confetti."
    ),
)
FAMILY_IDS = tuple(family.id for family in FAMILIES)
DEFAULT_FAMILY = "midnight"


@dataclass(frozen=True)
class BuiltinFrame:
    family: BuiltinFamily
    template_key: str

    @property
    def id(self) -> str:
        return str(uuid.uuid5(BUILTIN_NAMESPACE, f"{self.family.id}/{self.template_key}"))

    @property
    def name(self) -> str:
        return self.family.name

    @property
    def filename(self) -> str:
        return f"{self.family.id}.{self.template_key}.png"

    def read(self, directory: Path = BUILTIN_DIRECTORY) -> bytes:
        return (directory / self.filename).read_bytes()


def builtin_frames() -> tuple[BuiltinFrame, ...]:
    return tuple(BuiltinFrame(family, key) for family in FAMILIES for key in LAYOUTS)


def builtin_frame_id(family_id: str, template_key: str) -> str:
    family = next(f for f in FAMILIES if f.id == family_id)
    return BuiltinFrame(family, template_key).id
