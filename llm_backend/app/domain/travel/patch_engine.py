from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from app.schemas.itinerary_v1 import ChangeSummary, ItinerarySlot, ItineraryV1

from app.domain.travel.rules import PATCH_RULES, PatchRules

PatchOpType = Literal["replace_slot", "delete_slot", "insert_slot", "update_constraint"]


@dataclass(slots=True)
class PatchOp:
    op_type: PatchOpType
    day_index: int | None = None
    slot_name: str | None = None
    new_activity: str | None = None
    budget: float | None = None


class TravelPatchEngine:
    """T-M2-012 baseline patch engine (rule-based, minimal op set). 规则与文案见 patch_rules.py。"""

    def __init__(self, rules: PatchRules | None = None):
        self._rules = rules or PATCH_RULES
        self._slot_map = dict(self._rules.slot_aliases)

    def apply_edit_query(self, *, query: str, itinerary: dict[str, Any]) -> dict[str, Any]:
        """Parse NL edit query, apply patch locally, validate and return updated itinerary."""
        r = self._rules
        try:
            current = ItineraryV1.model_validate(deepcopy(itinerary))
        except Exception as exc:
            return {
                "ok": False,
                "message": r.msg_invalid_itinerary.format(detail=str(exc)),
            }

        op = self._parse_operation(query)
        if not op:
            return {"ok": False, "message": r.msg_no_operation}

        changed_days: list[int] = []
        diff_items: list[str] = []

        if op.op_type == "update_constraint":
            if op.budget is None:
                return {"ok": False, "message": r.msg_budget_no_value}
            current.budget_summary.total_estimate = float(op.budget)
            current.trip_profile.constraints.budget_range = r.budget_range_template.format(
                budget=int(op.budget)
            )
            changed_days = [day.day_index for day in current.days]
            diff_items.append(r.diff_budget_updated.format(budget=int(op.budget)))
        else:
            if op.day_index is None:
                return {"ok": False, "message": r.msg_need_day}
            day = self._find_day(current.model_dump(mode="python"), op.day_index)
            if not day:
                return {"ok": False, "message": r.msg_day_not_found.format(day_index=op.day_index)}
            slot_idx, slot_label = self._locate_slot(day, op.slot_name)

            if op.op_type == "delete_slot":
                if slot_idx is None:
                    return {"ok": False, "message": r.msg_delete_need_slot}
                if len(day["slots"]) <= 1:
                    return {"ok": False, "message": r.msg_delete_min_slots}
                removed = day["slots"].pop(slot_idx)
                changed_days = [op.day_index]
                diff_items.append(
                    r.diff_slot_deleted.format(day_index=op.day_index, slot=removed["slot"])
                )
            elif op.op_type == "replace_slot":
                if slot_idx is None:
                    return {"ok": False, "message": r.msg_replace_need_slot}
                if not op.new_activity:
                    return {"ok": False, "message": r.msg_replace_need_activity}
                old_activity = day["slots"][slot_idx]["activity"]
                day["slots"][slot_idx]["activity"] = op.new_activity
                changed_days = [op.day_index]
                slot_display = slot_label or day["slots"][slot_idx]["slot"]
                diff_items.append(
                    r.diff_slot_replaced.format(
                        day_index=op.day_index,
                        slot=slot_display,
                        old_activity=old_activity,
                        new_activity=op.new_activity,
                    )
                )
            elif op.op_type == "insert_slot":
                if not op.new_activity:
                    return {"ok": False, "message": r.msg_insert_need_activity}
                insert_label = slot_label or r.default_slot_label
                new_slot = ItinerarySlot(slot=insert_label, activity=op.new_activity).model_dump(
                    mode="python"
                )
                if slot_idx is None:
                    day["slots"].append(new_slot)
                else:
                    day["slots"].insert(slot_idx + 1, new_slot)
                changed_days = [op.day_index]
                diff_items.append(
                    r.diff_slot_inserted.format(
                        day_index=op.day_index, slot=insert_label, activity=op.new_activity
                    )
                )

            full_dict = current.model_dump(mode="python")
            for idx, item in enumerate(full_dict["days"]):
                if item["day_index"] == op.day_index:
                    full_dict["days"][idx] = day
                    break
            try:
                current = ItineraryV1.model_validate(full_dict)
            except Exception as exc:
                return {
                    "ok": False,
                    "message": r.msg_validate_failed.format(detail=str(exc)),
                }

        current.base_revision_id = current.revision_id
        current.revision_id = str(uuid.uuid4())
        current.change_summary = ChangeSummary(
            changed_days=sorted(set(changed_days)),
            diff_items=diff_items,
        )

        impact_level = self._impact_level(changed_days=changed_days, total_days=len(current.days))
        message = (
            r.msg_edit_done_local.format(impact_level=impact_level)
            if diff_items
            else r.msg_edit_done.format(impact_level=impact_level)
        )
        if diff_items:
            message = f"{message} 本轮变更：{r.msg_diff_join.join(diff_items)}"

        return {
            "ok": True,
            "itinerary": current.model_dump(mode="json"),
            "change_summary": current.change_summary.model_dump(mode="json"),
            "changed_days": sorted(set(changed_days)),
            "message": message,
        }

    def _parse_operation(self, query: str) -> PatchOp | None:
        q = (query or "").strip()
        lower_q = q.lower()
        r = self._rules
        day_index = self._extract_day_index(q)
        slot_name = self._extract_slot_name(q)

        budget = self._extract_budget(q)
        if budget is not None:
            return PatchOp(op_type="update_constraint", budget=budget)

        if any(hint in lower_q or hint in q for hint in r.delete_hints):
            return PatchOp(op_type="delete_slot", day_index=day_index, slot_name=slot_name)
        if any(hint in lower_q or hint in q for hint in r.replace_hints):
            return PatchOp(
                op_type="replace_slot",
                day_index=day_index,
                slot_name=slot_name,
                new_activity=self._extract_new_activity(q),
            )
        if any(hint in lower_q or hint in q for hint in r.insert_hints):
            return PatchOp(
                op_type="insert_slot",
                day_index=day_index,
                slot_name=slot_name,
                new_activity=self._extract_new_activity(q),
            )
        return None

    def _extract_day_index(self, query: str) -> int | None:
        match = self._rules.day_pattern.search(query or "")
        if not match:
            return None
        raw = match.group(1) or match.group(2)
        return int(raw) if raw else None

    def _extract_slot_name(self, query: str) -> str | None:
        lower_q = (query or "").lower()
        for alias, canonical in self._slot_map.items():
            if alias in lower_q or alias in query:
                return canonical
        return None

    def _extract_new_activity(self, query: str) -> str | None:
        for pattern in self._rules.activity_patterns:
            match = pattern.search(query)
            if match:
                value = (match.group(1) or "").strip()
                if value:
                    return value
        return None

    def _extract_budget(self, query: str) -> float | None:
        match = self._rules.budget_pattern.search(query or "")
        if not match:
            return None
        return float(match.group(1))

    @staticmethod
    def _find_day(itinerary: dict[str, Any], day_index: int) -> dict[str, Any] | None:
        for day in itinerary.get("days", []):
            if int(day.get("day_index", -1)) == day_index:
                return day
        return None

    @staticmethod
    def _locate_slot(day: dict[str, Any], slot_name: str | None) -> tuple[int | None, str | None]:
        if slot_name is None:
            return None, None
        for idx, slot in enumerate(day.get("slots", [])):
            if slot.get("slot") == slot_name:
                return idx, slot_name
        return None, slot_name

    def _impact_level(self, *, changed_days: list[int], total_days: int) -> str:
        r = self._rules
        if not changed_days:
            return "unknown"
        ratio = len(set(changed_days)) / max(total_days, 1)
        if ratio <= r.local_threshold:
            return "local"
        if ratio <= r.adjacent_threshold:
            return "adjacent"
        return "broad"
