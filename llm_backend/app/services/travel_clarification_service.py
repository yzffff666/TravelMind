import json
import re
from typing import Any, Dict, List, Tuple

from app.domain.travel.clarification_rules import (
    CLARIFICATION_STAGE_NAME,
    CLARIFICATION_MSG_HARD_AND_SOFT,
    CLARIFICATION_MSG_HARD_ONLY,
    FIELD_LABELS,
    GUIDED_FIELD_HINTS,
    HARD_REQUIRED_FIELDS,
    SOFT_RECOMMENDED_FIELDS,
    SSE_EVENT_STAGE_PROGRESS,
    SSE_EVENT_STAGE_START,
)
from app.domain.travel.draft_builder import (
    extract_budget,
    extract_days,
    extract_destination,
    extract_traveler_type,
)

_VALUE_KEYS = ("destination", "duration", "budget", "travelers")


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

    def start_new(self, thread_id: str, query: str) -> Dict[str, Any]:
        values = self._extract_values(query)
        missing_hard = self._missing_hard_fields(values)
        missing_soft = self._missing_soft_fields(values)

        if missing_hard:
            self._pending[thread_id] = {
                "initial_query": query,
                "values": values,
                "followups": [],
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
        merged = self._merge_values(pending["values"], delta)
        missing_hard = self._missing_hard_fields(merged)
        missing_soft = self._missing_soft_fields(merged)

        pending["values"] = merged
        pending["followups"].append(query)

        if missing_hard:
            return {
                "has_pending": True,
                "need_clarification": True,
                "missing_hard": missing_hard,
                "missing_soft": missing_soft,
            }

        combined_query = self._build_combined_query(merged)
        self._pending.pop(thread_id, None)
        return {
            "has_pending": True,
            "need_clarification": False,
            "combined_query": combined_query,
        }

    def get_constraint_context(self, thread_id: str) -> tuple[str, str]:
        """Return (known_text, missing_text) for LLM guided prompt."""
        pending = self._pending.get(thread_id)
        if not pending:
            return ("\u6682\u65e0", "\u76ee\u7684\u5730\u3001\u5929\u6570\u3001\u9884\u7b97")

        values = pending["values"]

        known_parts: list[str] = []
        if values.get("destination"):
            known_parts.append(f"\u76ee\u7684\u5730: {values['destination']}")
        if values.get("duration") is not None:
            known_parts.append(f"\u5929\u6570: {values['duration']}\u5929")
        if values.get("budget") is not None:
            known_parts.append(f"\u9884\u7b97: {int(values['budget'])}\u5143")
        if values.get("travelers"):
            known_parts.append(f"\u51fa\u884c\u4eba\u7fa4: {values['travelers']}")

        missing_parts: list[str] = []
        for field in HARD_REQUIRED_FIELDS:
            if values.get(field) is None:
                missing_parts.append(GUIDED_FIELD_HINTS.get(field, FIELD_LABELS[field]))

        known_text = "\u3001".join(known_parts) if known_parts else "\u6682\u65e0"
        missing_text = "\u3001".join(missing_parts) if missing_parts else "\u65e0"
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

    # ------------------------------------------------------------------
    # Legacy helpers (still used by /travel/resume template path)
    # ------------------------------------------------------------------

    def build_clarification_payload(self, missing_hard: List[str], missing_soft: List[str]) -> Dict[str, Any]:
        clarification_text = self._build_clarification_message(missing_hard, missing_soft)
        return {
            "stage": CLARIFICATION_STAGE_NAME,
            "missing_required": missing_hard,
            "missing_optional": missing_soft,
            "message": clarification_text,
        }

    def build_clarification_stream(self, thread_id: str, missing_hard: List[str], missing_soft: List[str]):
        payload = self.build_clarification_payload(missing_hard=missing_hard, missing_soft=missing_soft)
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

    def _build_clarification_message(self, missing_hard: List[str], missing_soft: List[str]) -> str:
        hard_text = "\u3001".join(FIELD_LABELS[key] for key in missing_hard)
        if missing_soft:
            soft_text = "\u3001".join(FIELD_LABELS[key] for key in missing_soft)
            return CLARIFICATION_MSG_HARD_AND_SOFT.format(
                hard_text=hard_text,
                soft_text=soft_text,
            )
        return CLARIFICATION_MSG_HARD_ONLY.format(hard_text=hard_text)

    @staticmethod
    def _sse_line(payload: Any) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
