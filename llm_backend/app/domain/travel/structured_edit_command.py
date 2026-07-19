"""Safe bridge from Structured QP output to the existing PatchOp control plane.

The model may describe *which constraints* should drive replanning, but it may
not inject an arbitrary POI/activity string into an itinerary. Every accepted
command is converted to ``REPLAN_DAY`` and must later be fulfilled by the
candidate-grounded DayReplanService.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.domain.travel.patch_engine import PatchOp, PatchOpType, has_mutation_intent


_ENGLISH_MUTATION_PATTERN = re.compile(
    r"\b(change|modify|adjust|replace|switch|swap|remove|delete|add|insert|make|move|reschedule)\b",
    re.IGNORECASE,
)
_SLOT_LABELS = {"上午", "下午", "晚上"}
_PREFERENCE_CONSTRAINTS = (
    ("indoor", ("indoor", "室内", "避雨", "博物馆", "美术馆", "展馆", "museum")),
    ("relaxed", ("relaxed", "轻松", "慢节奏", "别太赶", "少走路", "easy")),
    ("food", ("food", "美食", "吃喝", "小吃", "餐厅")),
    ("culture", ("culture", "文化", "人文", "历史", "艺术")),
)


@dataclass(frozen=True, slots=True)
class StructuredEditCommand:
    """A bounded replan request derived from a verified Structured QP result."""

    target_day: int
    target_slot: str | None
    constraints: tuple[str, ...]
    raw_request: str

    def to_patch_op(self) -> PatchOp:
        return PatchOp(
            op=PatchOpType.REPLAN_DAY,
            day_index=self.target_day,
            payload={
                "constraints": list(self.constraints),
                "raw_request": self.raw_request,
                "target_slot": self.target_slot,
                "execution_source": "structured_qp",
            },
        )


def build_structured_edit_command(
    qp_output: dict[str, Any] | None,
    *,
    utterance: str,
    current_itinerary: dict[str, Any],
) -> StructuredEditCommand | None:
    """Return a safe candidate-grounded replan command, or ``None``.

    A missing command deliberately falls back to the legacy deterministic
    parser. We only bridge model output when it has a concrete day and at least
    one planner-safe constraint.
    """
    if not qp_output:
        return None
    if qp_output.get("qp_source") != "llm" or qp_output.get("intent") != "edit":
        return None
    if qp_output.get("safety_level") != "safe":
        return None
    if not _has_explicit_mutation(utterance):
        return None

    target_day = qp_output.get("target_day")
    total_days = len(current_itinerary.get("days") or [])
    if not isinstance(target_day, int) or not 1 <= target_day <= total_days:
        return None

    target_slot = qp_output.get("target_slot")
    if target_slot not in _SLOT_LABELS:
        target_slot = None

    constraints = _planner_constraints(qp_output)
    if not constraints:
        return None
    return StructuredEditCommand(
        target_day=target_day,
        target_slot=target_slot,
        constraints=tuple(constraints),
        raw_request=utterance,
    )


def _has_explicit_mutation(utterance: str) -> bool:
    return has_mutation_intent(utterance) or bool(_ENGLISH_MUTATION_PATTERN.search(utterance or ""))


def _planner_constraints(qp_output: dict[str, Any]) -> list[str]:
    constraints: list[str] = []
    for value in qp_output.get("edit_constraints") or []:
        normalized = str(value).strip().lower()
        if normalized in {"indoor", "relaxed", "food", "culture"} and normalized not in constraints:
            constraints.append(normalized)

    qp_constraints = qp_output.get("constraints") or {}
    if qp_constraints.get("pace") == "relaxed" and "relaxed" not in constraints:
        constraints.append("relaxed")
    preferences = " ".join(str(value).lower() for value in (qp_constraints.get("preferences") or []))
    for constraint, hints in _PREFERENCE_CONSTRAINTS:
        if constraint not in constraints and any(hint in preferences for hint in hints):
            constraints.append(constraint)
    return constraints
