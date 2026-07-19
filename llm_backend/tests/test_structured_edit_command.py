"""Safety tests for the Structured QP -> candidate replan command bridge."""
from __future__ import annotations

import uuid

import pytest

from app.domain.travel.patch_engine import PatchOpType
from app.domain.travel.structured_edit_command import build_structured_edit_command


def _itinerary(days: int = 3) -> dict:
    return {
        "itinerary_id": str(uuid.uuid4()),
        "days": [{"day_index": index, "slots": []} for index in range(1, days + 1)],
    }


def _qp_output(**overrides) -> dict:
    output = {
        "qp_source": "llm",
        "intent": "edit",
        "safety_level": "safe",
        "target_day": 2,
        "target_slot": "下午",
        "edit_constraints": ["indoor"],
        "constraints": {"preferences": [], "pace": None},
    }
    output.update(overrides)
    return output


def test_structured_edit_command_maps_bounded_fields_to_replan_op():
    command = build_structured_edit_command(
        _qp_output(),
        utterance="把第二天下午改成室内博物馆",
        current_itinerary=_itinerary(),
    )

    assert command is not None
    assert command.target_day == 2
    assert command.target_slot == "下午"
    assert command.constraints == ("indoor",)
    op = command.to_patch_op()
    assert op.op == PatchOpType.REPLAN_DAY
    assert op.day_index == 2
    assert op.payload == {
        "constraints": ["indoor"],
        "raw_request": "把第二天下午改成室内博物馆",
        "target_slot": "下午",
        "execution_source": "structured_qp",
    }


def test_structured_edit_command_derives_safe_constraints_from_profile():
    command = build_structured_edit_command(
        _qp_output(
            edit_constraints=[],
            target_slot=None,
            constraints={"preferences": ["文化", "美食"], "pace": "relaxed"},
        ),
        utterance="把第二天调整得轻松一点，多一些文化和美食",
        current_itinerary=_itinerary(),
    )

    assert command is not None
    assert command.target_slot is None
    assert command.constraints == ("relaxed", "food", "culture")


def test_structured_edit_command_accepts_explicit_english_mutation():
    command = build_structured_edit_command(
        _qp_output(edit_constraints=["relaxed"]),
        utterance="Please make day 2 afternoon more relaxed.",
        current_itinerary=_itinerary(),
    )

    assert command is not None
    assert command.constraints == ("relaxed",)


@pytest.mark.parametrize(
    ("utterance", "overrides"),
    [
        ("第三天下午去哪里", {}),
        ("把第二天改成室内", {"qp_source": "rule"}),
        ("把第二天改成室内", {"intent": "qa"}),
        ("把第二天改成室内", {"safety_level": "blocked"}),
        ("把第二天改成室内", {"target_day": 99}),
        ("把第二天改一下", {"edit_constraints": [], "constraints": {"preferences": [], "pace": None}}),
    ],
)
def test_structured_edit_command_refuses_unsafe_or_unbounded_input(utterance, overrides):
    assert build_structured_edit_command(
        _qp_output(**overrides),
        utterance=utterance,
        current_itinerary=_itinerary(),
    ) is None
