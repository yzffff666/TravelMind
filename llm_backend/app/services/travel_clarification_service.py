import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from app.domain.travel.clarification_rules import (
    CLARIFICATION_STAGE_NAME,
    DEFAULT_DAILY_BUDGET,
    DEFAULT_DURATION_DAYS,
    FIELD_LABELS,
    FLEXIBLE_ANSWER_PATTERNS,
    GUIDED_FIELD_HINTS,
    HARD_REQUIRED_FIELDS,
    MIN_DEFAULT_BUDGET,
    SOFT_RECOMMENDED_FIELDS,
    SSE_EVENT_STAGE_PROGRESS,
    SSE_EVENT_STAGE_START,
)
from app.domain.travel.language_policy import localized_text
from app.domain.travel.draft_builder import (
    extract_budget,
    extract_days,
    extract_destination,
    extract_traveler_type,
)

_VALUE_KEYS = ("destination", "duration", "budget", "travelers")
_ENGLISH_FIELD_LABELS = {
    "destination": "destination city",
    "duration": "trip length or date range",
    "budget": "budget range",
    "travelers": "travel party",
}


class TravelClarificationService:
    """Value-based clarification gate with in-memory pending state.

    Tracks actual extracted *values* so that detection and extraction are
    always consistent -- if a value can't be extracted, it is not considered
    present, preventing premature itinerary generation.
    """

    def __init__(self) -> None:
        self._pending: Dict[str, Dict[str, Any]] = {}

    def has_pending(self, thread_id: str) -> bool:
        return thread_id in self._pending

    def clear_pending(self, thread_id: str) -> None:
        self._pending.pop(thread_id, None)

    def snapshot_pending(self, thread_id: str) -> Dict[str, Any] | None:
        pending = self._pending.get(thread_id)
        return deepcopy(pending) if pending is not None else None

    def restore_pending(self, thread_id: str, snapshot: Dict[str, Any] | None) -> None:
        if not snapshot:
            self.clear_pending(thread_id)
            return
        values = snapshot.get("values")
        if not isinstance(values, dict):
            raise ValueError("clarification snapshot values must be a dict")
        self._pending[thread_id] = {
            "initial_query": str(snapshot.get("initial_query") or ""),
            "values": {key: values.get(key) for key in _VALUE_KEYS},
            "followups": [str(item) for item in snapshot.get("followups") or []],
            "asked_fields": [
                str(item)
                for item in snapshot.get("asked_fields") or []
                if str(item) in HARD_REQUIRED_FIELDS
            ],
            "assumptions": [str(item) for item in snapshot.get("assumptions") or []],
        }

    def start_new(self, thread_id: str, query: str) -> Dict[str, Any]:
        values = self._extract_values(query)
        missing_hard = self._missing_hard_fields(values)
        missing_soft = self._missing_soft_fields(values)

        if missing_hard:
            self._pending[thread_id] = {
                "initial_query": query,
                "values": values,
                "followups": [],
                "asked_fields": list(missing_hard),
                "assumptions": [],
            }

        return {
            "need_clarification": bool(missing_hard),
            "missing_hard": missing_hard,
            "missing_soft": missing_soft,
        }

    def continue_pending(self, thread_id: str, query: str) -> Dict[str, Any]:
        pending = self._pending.get(thread_id)
        if not pending:
            return {"has_pending": False}

        delta = self._extract_values(query)
        if (
            delta.get("budget") is None
            and "budget" in (pending.get("asked_fields") or [])
        ):
            # A short reply such as "中等就行" is unambiguous when the
            # clarification question currently asks only for budget.
            delta["budget"] = extract_budget(f"预算 {query}")
        merged = self._merge_values(pending["values"], delta)
        assumptions = list(pending.get("assumptions") or [])
        if self._is_flexible_answer(query):
            if merged.get("duration") is None:
                merged["duration"] = DEFAULT_DURATION_DAYS
                assumptions.append("duration_defaulted_from_flexible_answer")
            if merged.get("budget") is None:
                duration = int(merged.get("duration") or DEFAULT_DURATION_DAYS)
                merged["budget"] = max(MIN_DEFAULT_BUDGET, duration * DEFAULT_DAILY_BUDGET)
                assumptions.append("budget_defaulted_from_flexible_answer")

        missing_hard = self._missing_hard_fields(merged)
        missing_soft = self._missing_soft_fields(merged)

        pending["values"] = merged
        pending["followups"].append(query)
        pending["assumptions"] = list(dict.fromkeys(assumptions))
        pending["asked_fields"] = list(
            dict.fromkeys([*(pending.get("asked_fields") or []), *missing_hard])
        )

        if missing_hard:
            return {
                "has_pending": True,
                "need_clarification": True,
                "missing_hard": missing_hard,
                "missing_soft": missing_soft,
                "assumptions": list(pending["assumptions"]),
            }

        combined_query = self._build_combined_query(merged)
        final_assumptions = list(pending["assumptions"])
        self._pending.pop(thread_id, None)
        return {
            "has_pending": True,
            "need_clarification": False,
            "combined_query": combined_query,
            "assumptions": final_assumptions,
        }

    def get_constraint_context(
        self,
        thread_id: str,
        response_language: str = "zh-CN",
    ) -> tuple[str, str]:
        """Return (known_text, missing_text) for LLM guided prompt."""
        is_english = response_language == "en"
        labels = _ENGLISH_FIELD_LABELS if is_english else FIELD_LABELS
        separator = ", " if is_english else "\u3001"
        pending = self._pending.get(thread_id)
        if not pending:
            if is_english:
                return ("none", "destination city, trip length, budget range")
            return ("\u6682\u65e0", "\u76ee\u7684\u5730\u3001\u5929\u6570\u3001\u9884\u7b97")

        values = pending["values"]

        known_parts: list[str] = []
        if values.get("destination"):
            label = "destination" if is_english else "\u76ee\u7684\u5730"
            known_parts.append(f"{label}: {values['destination']}")
        if values.get("duration") is not None:
            if is_english:
                known_parts.append(f"trip length: {values['duration']} days")
            else:
                known_parts.append(f"\u5929\u6570: {values['duration']}\u5929")
        if values.get("budget") is not None:
            if is_english:
                known_parts.append(f"budget: {int(values['budget'])} CNY")
            else:
                known_parts.append(f"\u9884\u7b97: {int(values['budget'])}\u5143")
        if values.get("travelers"):
            label = "travel party" if is_english else "\u51fa\u884c\u4eba\u7fa4"
            known_parts.append(f"{label}: {values['travelers']}")

        missing_parts: list[str] = []
        for field in HARD_REQUIRED_FIELDS:
            if values.get(field) is None:
                missing_parts.append(
                    labels[field]
                    if is_english
                    else GUIDED_FIELD_HINTS.get(field, FIELD_LABELS[field])
                )

        known_text = separator.join(known_parts) if known_parts else (
            "none" if is_english else "\u6682\u65e0"
        )
        missing_text = separator.join(missing_parts) if missing_parts else (
            "none" if is_english else "\u65e0"
        )
        if is_english:
            known_text = f"Known constraints: {known_text}"
            missing_text = f"Missing constraints: {missing_text}"
        return (known_text, missing_text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_values(text: str) -> Dict[str, Any]:
        """Extract actual constraint values using the same functions as QP."""
        return {
            "destination": extract_destination(text),
            "duration": extract_days(text),
            "budget": extract_budget(text),
            "travelers": extract_traveler_type(text),
        }

    @staticmethod
    def _merge_values(base: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, Any]:
        """Merge values: latest non-None wins (allows user to change mind)."""
        result = dict(base)
        for key in _VALUE_KEYS:
            v = delta.get(key)
            if v is not None:
                result[key] = v
        return result

    @staticmethod
    def _missing_hard_fields(values: Dict[str, Any]) -> List[str]:
        return [f for f in HARD_REQUIRED_FIELDS if values.get(f) is None]

    @staticmethod
    def _missing_soft_fields(values: Dict[str, Any]) -> List[str]:
        return [f for f in SOFT_RECOMMENDED_FIELDS if values.get(f) is None]

    @staticmethod
    def _build_combined_query(values: Dict[str, Any]) -> str:
        """Construct a clean, structured query from extracted values."""
        parts: list[str] = []
        if values.get("destination"):
            parts.append(f"\u53bb{values['destination']}")
        if values.get("duration") is not None:
            parts.append(f"\u73a9{values['duration']}\u5929")
        if values.get("budget") is not None:
            parts.append(f"\u9884\u7b97{int(values['budget'])}\u5143")
        if values.get("travelers"):
            parts.append(f"{values['travelers']}\u51fa\u884c")
        return "\uff0c".join(parts) if parts else ""

    @staticmethod
    def _is_flexible_answer(query: str) -> bool:
        normalized = (query or "").strip()
        return any(re.fullmatch(pattern, normalized, re.IGNORECASE) for pattern in FLEXIBLE_ANSWER_PATTERNS)

    # ------------------------------------------------------------------
    # Legacy helpers (still used by /travel/resume template path)
    # ------------------------------------------------------------------

    def build_clarification_payload(
        self,
        missing_hard: List[str],
        missing_soft: List[str],
        response_language: str = "zh-CN",
    ) -> Dict[str, Any]:
        clarification_text = self._build_clarification_message(
            missing_hard,
            missing_soft,
            response_language=response_language,
        )
        return {
            "stage": CLARIFICATION_STAGE_NAME,
            "missing_required": missing_hard,
            "missing_optional": missing_soft,
            "message": clarification_text,
            "response_language": response_language,
        }

    def build_clarification_stream(
        self,
        thread_id: str,
        missing_hard: List[str],
        missing_soft: List[str],
        response_language: str = "zh-CN",
    ):
        payload = self.build_clarification_payload(
            missing_hard=missing_hard,
            missing_soft=missing_soft,
            response_language=response_language,
        )
        clarification_text = payload["message"]

        async def _stream():
            yield self._sse_line(
                {
                    "event": SSE_EVENT_STAGE_START,
                    "stage": CLARIFICATION_STAGE_NAME,
                    "conversation_id": thread_id,
                }
            )
            yield self._sse_line(
                {
                    "event": SSE_EVENT_STAGE_PROGRESS,
                    "stage": payload["stage"],
                    "conversation_id": thread_id,
                    "missing_required": payload["missing_required"],
                    "missing_optional": payload["missing_optional"],
                    "message": payload["message"],
                }
            )
            yield self._sse_line(clarification_text)

        return _stream()

    def _build_clarification_message(
        self,
        missing_hard: List[str],
        missing_soft: List[str],
        *,
        response_language: str = "zh-CN",
    ) -> str:
        is_english = response_language == "en"
        labels = _ENGLISH_FIELD_LABELS if is_english else FIELD_LABELS
        separator = ", " if is_english else "\u3001"
        hard_text = separator.join(labels[key] for key in missing_hard)
        if missing_soft:
            soft_text = separator.join(labels[key] for key in missing_soft)
            return localized_text(
                "clarification_hard_and_soft",
                response_language,
                hard_text=hard_text,
                soft_text=soft_text,
            )
        return localized_text(
            "clarification_hard_only",
            response_language,
            hard_text=hard_text,
        )

    @staticmethod
    def _sse_line(payload: Any) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
