"""Template registry: approved coordinates, invariants and frame requirements."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from photobooth.modules.templates.domain import (
    PhotoTemplate,
    Rect,
    SlotDefinition,
    TemplateError,
    TemplateNotFoundError,
)
from photobooth.modules.templates.repository import DEFAULT_DIRECTORY, JsonTemplateRepository

EXPECTED = {
    "strip_2x6": {
        "inches": (2, 6),
        "canvas": (600, 1800),
        "photos": 3,
        "captures": 6,
        "outputs": 2,
        "groups": ((1, 2, 3), (4, 5, 6)),
        "slots": [(30, 45, 540, 405), (30, 480, 540, 405), (30, 915, 540, 405)],
        "branding": Rect(0, 1350, 600, 450),
    },
    "print_3x4": {
        "inches": (3, 4),
        "canvas": (900, 1200),
        "photos": 2,
        "captures": 2,
        "outputs": 1,
        "groups": ((1, 2),),
        "slots": [(45, 45, 810, 540), (45, 615, 810, 540)],
        "branding": None,
    },
    "print_4x6": {
        "inches": (4, 6),
        "canvas": (1200, 1800),
        "photos": 4,
        "captures": 4,
        "outputs": 1,
        "groups": ((1, 2, 3, 4),),
        "slots": [
            (30, 30, 555, 740),
            (615, 30, 555, 740),
            (30, 800, 555, 740),
            (615, 800, 555, 740),
        ],
        "branding": Rect(0, 1570, 1200, 230),
    },
}


@pytest.fixture(scope="module")
def repository() -> JsonTemplateRepository:
    return JsonTemplateRepository()


def test_registry_contains_exactly_the_three_v1_templates(
    repository: JsonTemplateRepository,
) -> None:
    assert sorted((t.key, t.version) for t in repository.all()) == [
        ("print_3x4", 1),
        ("print_4x6", 1),
        ("strip_2x6", 1),
    ]


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_templates_match_approved_plan_coordinates(
    repository: JsonTemplateRepository, key: str
) -> None:
    template = repository.get(key)
    expected = EXPECTED[key]
    assert (template.width_in, template.height_in) == expected["inches"]
    assert (template.width_px, template.height_px) == expected["canvas"]
    assert template.dpi == 300
    assert template.photos_per_output == expected["photos"]
    assert template.captures_per_session == expected["captures"]
    assert template.outputs_per_session == expected["outputs"]
    assert template.output_capture_groups == expected["groups"]
    assert [(s.rect.x, s.rect.y, s.rect.w, s.rect.h) for s in template.slots] == expected["slots"]
    assert template.branding_area == expected["branding"]
    assert template.safe_area_inset == 36
    assert template.bleed == 0
    assert template.frame_rules.mode == "RGBA"
    assert template.frame_rules.slot_min_transparency == 0.95


def test_2x6_aspect_ratios(repository: JsonTemplateRepository) -> None:
    assert {s.aspect_label for s in repository.get("strip_2x6").slots} == {"4:3"}
    assert {s.aspect_label for s in repository.get("print_3x4").slots} == {"3:2"}
    assert {s.aspect_label for s in repository.get("print_4x6").slots} == {"3:4"}


def test_get_by_version_and_unknown(repository: JsonTemplateRepository) -> None:
    assert repository.get("strip_2x6", 1).version == 1
    with pytest.raises(TemplateNotFoundError):
        repository.get("strip_2x6", 2)
    with pytest.raises(TemplateNotFoundError):
        repository.get("poster_8x10")


def test_frame_requirements_state_every_designer_fact(repository: JsonTemplateRepository) -> None:
    text = "\n".join(repository.get("strip_2x6").frame_requirements())
    for fact in (
        "PNG with transparency (RGBA)",
        "exactly 600 x 1800 px (2 x 6 in at 300 DPI)",
        "at least 95% transparent",
        "Photo 1: x=30, y=45, w=540, h=405 px",
        "Photo 3: x=30, y=915, w=540, h=405 px",
        "Safe area: keep text and logos inside x 36-564, y 36-1764 px",
        "Branding area: x=0, y=1350, w=600, h=450 px",
        "output 1 uses captures 1-3, output 2 uses captures 4-6",
        "Maximum file size 10 MB",
    ):
        assert fact in text, fact


def _mutate(template: PhotoTemplate, **changes: object) -> None:
    fields = {f.name: getattr(template, f.name) for f in dataclasses.fields(template)}
    fields.update(changes)
    PhotoTemplate(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"width_px": 601}, "width 601px"),
        ({"dpi": 150}, "!= 2.0in x 150dpi"),
        ({"output_capture_groups": ((1, 2, 3), (3, 4, 5))}, "exactly once"),
        ({"output_capture_groups": ((1, 2, 3),)}, "outputs_per_session"),
        ({"captures_per_session": 5}, "exactly once"),
        ({"photos_per_output": 2}, "photos_per_output"),
    ],
)
def test_invalid_definitions_are_rejected(
    repository: JsonTemplateRepository, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(TemplateError, match=message):
        _mutate(repository.get("strip_2x6"), **changes)


def test_overlapping_or_outside_slots_are_rejected(repository: JsonTemplateRepository) -> None:
    template = repository.get("strip_2x6")
    overlapping = (
        template.slots[0],
        SlotDefinition(2, Rect(30, 400, 540, 405)),
        template.slots[2],
    )
    with pytest.raises(TemplateError, match="overlap"):
        _mutate(template, slots=overlapping)
    outside = (template.slots[0], template.slots[1], SlotDefinition(3, Rect(30, 1500, 540, 405)))
    with pytest.raises(TemplateError, match="outside the canvas"):
        _mutate(template, slots=outside)


def test_repository_rejects_mismatched_file_names(tmp_path: Path) -> None:
    (tmp_path / "strip_2x6.v2.json").write_text(
        (DEFAULT_DIRECTORY / "strip_2x6.v1.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(TemplateError, match="declares strip_2x6 v1"):
        JsonTemplateRepository(tmp_path)
