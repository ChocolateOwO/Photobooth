"""The decoration a guest sends: what is accepted, how it is stored, what is refused."""

from __future__ import annotations

import json

import pytest

from photobooth.modules.decorations.domain import (
    FILTERS,
    MAX_STICKERS_PER_OUTPUT,
    DecorationError,
    parse_spec,
    read_canonical,
)

OFFERED = ("heart", "star")


def sticker(**overrides: object) -> dict[str, object]:
    return {"sticker": "heart", "output": 1, "x": 0.5, "y": 0.5, "size": 0.3, "rotation": 0} | (
        overrides
    )


def test_a_decoration_reads_back_exactly_as_it_was_stored() -> None:
    spec = parse_spec(
        {"filter": "sepia", "stickers": [sticker(), sticker(sticker="star", output=2, x=0.1)]},
        outputs=2,
        stickers=OFFERED,
    )
    assert read_canonical(spec.canonical()) == spec
    assert spec.on(2)[0].sticker == "star"


def test_equal_decorations_are_stored_as_the_same_text() -> None:
    a = parse_spec({"filter": "warm", "stickers": [sticker(x=0.123456)]}, 1, OFFERED)
    b = parse_spec(
        {"stickers": [sticker(x=0.12346, rotation=360)], "filter": "warm", "version": 1},
        1,
        OFFERED,
    )
    assert a.canonical() == b.canonical()
    assert json.loads(a.canonical())["stickers"][0]["x"] == 0.1235


def test_no_filter_and_no_stickers_is_no_decoration() -> None:
    assert parse_spec({}, 1, OFFERED).empty
    assert parse_spec({"filter": "none", "stickers": []}, 1, OFFERED).empty
    assert not parse_spec({"filter": "mono"}, 1, OFFERED).empty


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [(0, 0.0), (190, -170.0), (-180, 180.0), (540, 180.0), (-0.0, 0.0), (725.5, 5.5)],
)
def test_rotation_is_kept_between_minus_180_and_180(rotation: float, expected: float) -> None:
    spec = parse_spec({"stickers": [sticker(rotation=rotation)]}, 1, OFFERED)
    assert spec.stickers[0].rotation == expected


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"filter": "vintage"},
        {"filter": 3},
        {"version": 2},
        {"filters": "mono"},
        {"stickers": {}},
        {"stickers": ["heart"]},
        {"stickers": [sticker(sticker="skull")]},
        {"stickers": [sticker(output=3)]},
        {"stickers": [sticker(output=0)]},
        {"stickers": [sticker(output=True)]},
        {"stickers": [sticker(output=1.0)]},
        {"stickers": [sticker(x=1.01)]},
        {"stickers": [sticker(y=-0.01)]},
        {"stickers": [sticker(size=0.01)]},
        {"stickers": [sticker(size=1.5)]},
        {"stickers": [sticker(x="0.5")]},
        {"stickers": [sticker(x=float("nan"))]},
        {"stickers": [sticker(rotation=float("inf"))]},
        {"stickers": [sticker(rotation=1e9)]},
        {"stickers": [sticker(extra=1)]},
        {"stickers": [{"sticker": "heart", "output": 1, "x": 0.5, "y": 0.5, "size": 0.3}]},
    ],
)
def test_a_decoration_outside_the_rules_is_refused(raw: object) -> None:
    with pytest.raises(DecorationError):
        parse_spec(raw, outputs=2, stickers=OFFERED)


def test_a_photo_takes_at_most_its_share_of_stickers() -> None:
    full = [sticker() for _ in range(MAX_STICKERS_PER_OUTPUT)]
    parse_spec({"stickers": [*full, sticker(output=2)]}, 2, OFFERED)
    with pytest.raises(DecorationError):
        parse_spec({"stickers": [*full, sticker()]}, 2, OFFERED)


def test_every_filter_is_an_affine_colour_matrix_and_none_changes_nothing() -> None:
    keys = [preset.key for preset in FILTERS]
    assert keys == ["none", "mono", "sepia", "warm", "cool", "bright"]
    assert FILTERS[0].matrix == (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)
    for preset in FILTERS:
        assert len(preset.matrix) == 12
