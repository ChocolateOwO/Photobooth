"""Template definitions loaded from versioned JSON files (`<key>.v<version>.json`)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from photobooth.modules.templates.domain import (
    FrameRules,
    Orientation,
    PhotoTemplate,
    Rect,
    SlotDefinition,
    TemplateError,
    TemplateRepository,
)

FILE_NAME = re.compile(r"^(?P<key>[a-z0-9_]+)\.v(?P<version>\d+)\.json$")
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[2] / "templates_data"


def _rect(raw: dict[str, Any]) -> Rect:
    return Rect(x=int(raw["x"]), y=int(raw["y"]), w=int(raw["w"]), h=int(raw["h"]))


def parse_template(raw: dict[str, Any]) -> PhotoTemplate:
    try:
        return PhotoTemplate(
            key=str(raw["key"]),
            version=int(raw["version"]),
            name=str(raw["name"]),
            width_in=float(raw["physical"]["width_in"]),
            height_in=float(raw["physical"]["height_in"]),
            dpi=int(raw["dpi"]),
            width_px=int(raw["canvas"]["width"]),
            height_px=int(raw["canvas"]["height"]),
            orientation=Orientation(raw["orientation"]),
            photos_per_output=int(raw["photos_per_output"]),
            captures_per_session=int(raw["captures_per_session"]),
            outputs_per_session=int(raw["outputs_per_session"]),
            output_capture_groups=tuple(
                tuple(int(c) for c in group) for group in raw["output_capture_groups"]
            ),
            slots=tuple(
                SlotDefinition(
                    index=int(slot["index"]),
                    rect=_rect(slot),
                    fit=str(slot.get("fit", "cover")),
                    anchor=str(slot.get("anchor", "center")),
                )
                for slot in raw["slots"]
            ),
            safe_area_inset=int(raw["safe_area_inset"]),
            bleed=int(raw["bleed"]),
            branding_area=None if raw.get("branding_area") is None else _rect(raw["branding_area"]),
            frame_rules=FrameRules(**raw["frame_rules"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TemplateError(f"malformed template definition: {exc}") from exc


class JsonTemplateRepository(TemplateRepository):
    """Loads and validates every template file once; definitions are read-only afterwards."""

    def __init__(self, directory: Path = DEFAULT_DIRECTORY) -> None:
        templates: list[PhotoTemplate] = []
        seen: set[tuple[str, int]] = set()
        for path in sorted(directory.glob("*.json")):
            match = FILE_NAME.match(path.name)
            if match is None:
                raise TemplateError(f"unexpected template file name: {path.name}")
            template = parse_template(json.loads(path.read_text(encoding="utf-8")))
            expected = (match.group("key"), int(match.group("version")))
            if (template.key, template.version) != expected:
                raise TemplateError(f"{path.name} declares {template.key} v{template.version}")
            if expected in seen:
                raise TemplateError(f"duplicate template {expected}")
            seen.add(expected)
            templates.append(template)
        if not templates:
            raise TemplateError(f"no templates found in {directory}")
        self._templates = tuple(templates)

    def all(self) -> list[PhotoTemplate]:
        return list(self._templates)
