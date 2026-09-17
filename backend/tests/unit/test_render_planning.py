"""Output planning: captures map onto outputs exactly once (no reuse between 2x6 strips)."""

from __future__ import annotations

import pytest

from photobooth.modules.rendering.domain import CaptureRef, RenderError, plan_outputs
from photobooth.modules.templates.repository import JsonTemplateRepository

TEMPLATES = JsonTemplateRepository()


def _captures(count: int) -> list[CaptureRef]:
    return [CaptureRef(capture_id=f"cap-{i}", shot_index=i) for i in range(1, count + 1)]


def test_2x6_uses_six_unique_captures_split_1_3_and_4_6() -> None:
    plans = plan_outputs(TEMPLATES.get("strip_2x6"), _captures(6))
    assert [p.output_index for p in plans] == [1, 2]
    assert plans[0].capture_ids == ("cap-1", "cap-2", "cap-3")
    assert plans[1].capture_ids == ("cap-4", "cap-5", "cap-6")
    assert set(plans[0].capture_ids).isdisjoint(plans[1].capture_ids)
    assert [a.slot.index for a in plans[1].assignments] == [1, 2, 3]


def test_captures_given_out_of_order_are_placed_by_shot_index() -> None:
    shuffled = list(reversed(_captures(6)))
    plans = plan_outputs(TEMPLATES.get("strip_2x6"), shuffled)
    assert plans[0].capture_ids == ("cap-1", "cap-2", "cap-3")


@pytest.mark.parametrize(
    ("key", "count", "expected"),
    [
        ("print_3x4", 2, [("cap-1", "cap-2")]),
        ("print_4x6", 4, [("cap-1", "cap-2", "cap-3", "cap-4")]),
    ],
)
def test_single_output_templates(key: str, count: int, expected: list[tuple[str, ...]]) -> None:
    assert [p.capture_ids for p in plan_outputs(TEMPLATES.get(key), _captures(count))] == expected


def test_2x6_refuses_too_few_captures_instead_of_reusing() -> None:
    with pytest.raises(RenderError, match="needs 6 captures, got 3"):
        plan_outputs(TEMPLATES.get("strip_2x6"), _captures(3))


def test_the_same_capture_can_not_fill_two_shots() -> None:
    captures = _captures(6)
    captures[3] = CaptureRef(capture_id="cap-1", shot_index=4)
    with pytest.raises(RenderError, match="same capture"):
        plan_outputs(TEMPLATES.get("strip_2x6"), captures)


def test_shot_indexes_must_be_complete() -> None:
    captures = _captures(6)
    captures[5] = CaptureRef(capture_id="cap-6", shot_index=5)
    with pytest.raises(RenderError, match="shot indexes"):
        plan_outputs(TEMPLATES.get("strip_2x6"), captures)
