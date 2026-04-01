from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.domain.travel.clarification_rules import HARD_REQUIRED_FIELDS
from app.domain.travel.draft_builder import (
    extract_budget,
    extract_days,
    extract_destination,
    extract_traveler_type,
)
from app.domain.travel.qp_rules import QP_RULES

# 意图类型
IntentType = Literal["create", "edit", "qa", "reset"]
IntentDetailType = Literal["first_create", "edit_day", "qa_evidence", "qa_local", "reset_all"]

@dataclass(slots=True)
class QPConstraints:
    destination_city: str | None = None
    days: int | None = None
    budget: float | None = None
    traveler_type: str | None = None
    preferences: list[str] = field(default_factory=list)
    pace: str | None = None


@dataclass(slots=True)
class QPOutput:
    intent: IntentType
    intent_detail: IntentDetailType
    normalized_query: str
    recall_query: str
    constraints: QPConstraints
    constraint_presence: dict[str, bool]
    missing_required: list[str]
    rewrite_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload

# 旅行查询处理器
class TravelQueryProcessor:
    """QP baseline: intent + constraints extraction + recall-ready query."""

    # 处理查询
    def process(self, query: str) -> dict[str, Any]:
        # 标准化查询
        normalized = self._normalize_query(query)
        # 提取约束
        constraints = self._extract_constraints(normalized)
        # 约束存在性
        presence = {
            "destination": bool(constraints.destination_city),
            "duration": constraints.days is not None,
            "budget": constraints.budget is not None,
            "travelers": bool(constraints.traveler_type),
        }
        # 缺失的硬约束
        missing_required = [key for key in HARD_REQUIRED_FIELDS if not presence.get(key, False)]
        # 意图识别
        intent, intent_detail = self._detect_intent(normalized)
        # 召回查询
        recall_query = self._build_recall_query(normalized, constraints)

        # 返回查询结果
        return QPOutput(
            intent=intent,
            intent_detail=intent_detail,
            normalized_query=normalized,
            recall_query=recall_query,
            constraints=constraints,
            constraint_presence=presence,
            missing_required=missing_required,
        ).to_dict()

    # 标准化查询
    @staticmethod
    def _normalize_query(query: str) -> str:
        # Baseline rewrite: collapse whitespace for stable downstream matching.
        normalized = re.sub(r"\s+", " ", (query or "").strip())
        return normalized

    # 意图识别
    def _detect_intent(self, query: str) -> tuple[IntentType, IntentDetailType]:
        lower_q = query.lower()
        if any(self._contains_hint(query, lower_q, word) for word in QP_RULES.reset_hints):
            return "reset", "reset_all"
        if QP_RULES.edit_day_pattern.search(lower_q) or any(
            self._contains_hint(query, lower_q, word) for word in QP_RULES.edit_hints
        ):
            return "edit", "edit_day"
        if any(self._contains_hint(query, lower_q, word) for word in QP_RULES.evidence_qa_hints):
            return "qa", "qa_evidence"
        if QP_RULES.qa_question_pattern.search(query):
            return "qa", "qa_local"
        return "create", "first_create"

    @staticmethod
    def _contains_hint(raw_query: str, lower_query: str, hint: str) -> bool:
        """Chinese hints use substring; ASCII hints use whole-word match."""
        if hint.isascii():
            return bool(re.search(rf"\b{re.escape(hint.lower())}\b", lower_query))
        return hint in raw_query

    # 提取约束
    @staticmethod
    def _extract_constraints(query: str) -> QPConstraints:
        destination = extract_destination(query)
        days = extract_days(query)
        budget = extract_budget(query)
        traveler_type = extract_traveler_type(query)
        preferences = [item for item in QP_RULES.preference_keywords if item in query]
        pace = None
        for key, value in QP_RULES.pace_keywords.items():
            if key in query:
                pace = value
                break
        return QPConstraints(
            destination_city=destination,
            days=days,
            budget=budget,
            traveler_type=traveler_type,
            preferences=preferences,
            pace=pace,
        )

    # 构建召回查询
    @staticmethod
    def _build_recall_query(normalized_query: str, constraints: QPConstraints) -> str:
        # Keep original user wording while appending explicit constraints for recall/ranking.
        parts: list[str] = [normalized_query]
        if constraints.destination_city:
            parts.append(f"目的地:{constraints.destination_city}")
        if constraints.days is not None:
            parts.append(f"天数:{constraints.days}")
        if constraints.budget is not None:
            parts.append(f"预算:{int(constraints.budget)}")
        if constraints.traveler_type:
            parts.append(f"人群:{constraints.traveler_type}")
        if constraints.preferences:
            parts.append(f"偏好:{'/'.join(constraints.preferences)}")
        if constraints.pace:
            parts.append(f"节奏:{constraints.pace}")
        return QP_RULES.recall_joiner.join(parts)
