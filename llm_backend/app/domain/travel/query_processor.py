from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, Literal

from app.core.config import settings
from app.domain.travel.clarification_rules import HARD_REQUIRED_FIELDS
from app.domain.travel.draft_builder import (
    extract_budget,
    extract_days,
    extract_destination,
    extract_traveler_type,
)
from app.domain.travel.qp_rules import QP_RULES
from app.domain.travel.structured_qp import (
    LLMStructuredQPStrategy,
    StructuredQPContext,
    StructuredQPResult,
)

# 意图类型
IntentType = Literal["create", "edit", "qa", "reset", "chat"]
IntentDetailType = Literal["first_create", "edit_day", "qa_evidence", "qa_local", "reset_all", "general_chat"]

_ENGLISH_RESET_HINT_PATTERN = re.compile(
    r"\b(start over|begin again|clear (?:trip|itinerary)|new trip)\b",
    re.IGNORECASE,
)
_ENGLISH_EDIT_HINT_PATTERN = re.compile(
    r"\b(change|modify|adjust|replace|switch|swap|remove|delete|cancel|add|insert|make|move|reschedule)\b",
    re.IGNORECASE,
)
_ENGLISH_EVIDENCE_HINT_PATTERN = re.compile(
    r"\b(evidence|source|sources|reference|references)\b",
    re.IGNORECASE,
)
_TRAVEL_QA_TOPIC_PATTERN = re.compile(
    r"(第\s*(?:\d+|[一二两三四五六七八九十]+)\s*天|day\s*\d+|"
    r"行程|安排|景点|活动|门票|交通|地址|预算|花费|费用|推荐|证据|来源|链接|"
    r"itinerary|plan|activity|ticket|transit|transport|address|budget|cost|"
    r"recommendation|recommend|ref|reference|source|where|when|how\s+long)",
    re.IGNORECASE,
)

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
    qp_source: Literal["rule", "llm", "fallback"] = "rule"
    confidence: float | None = None
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


class StructuredQPStrategy(Protocol):
    async def classify(
        self,
        query: str,
        *,
        context: StructuredQPContext | None = None,
    ) -> StructuredQPResult:
        ...

# 旅行查询处理器
class TravelQueryProcessor:
    """QP baseline: intent + constraints extraction + recall-ready query."""

    def __init__(
        self,
        *,
        structured_strategy: StructuredQPStrategy | None = None,
        enable_structured_qp: bool | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        self._structured_strategy = structured_strategy
        self._enable_structured_qp = (
            settings.ENABLE_STRUCTURED_QP
            if enable_structured_qp is None
            else enable_structured_qp
        )
        self._confidence_threshold = (
            settings.STRUCTURED_QP_CONFIDENCE_THRESHOLD
            if confidence_threshold is None
            else confidence_threshold
        )

    # 处理查询
    def process(self, query: str) -> dict[str, Any]:
        """Synchronous rule baseline. Async callers may opt into Structured QP."""
        return self._process_rule(query)

    async def process_async(
        self,
        query: str,
        *,
        context: StructuredQPContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        baseline = self._process_rule(query)
        if not self._should_use_structured_qp(baseline):
            return baseline

        structured_context = self._coerce_context(context)
        try:
            result = await self._get_structured_strategy().classify(
                query,
                context=structured_context,
            )
        except Exception as exc:
            return self._with_metadata(
                baseline,
                qp_source="fallback",
                fallback_reason=f"{type(exc).__name__}: {exc}",
            )

        if result.confidence < self._confidence_threshold:
            return self._with_metadata(
                baseline,
                qp_source="fallback",
                confidence=result.confidence,
                fallback_reason="low_confidence",
            )

        return self._merge_structured_result(query, baseline, result)

    def _process_rule(self, query: str) -> dict[str, Any]:
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
        if intent != "create":
            # P0 missing fields only block itinerary creation. Read-only QA,
            # edits, reset, and chat should not carry clarification pressure
            # just because their text mentions a day number but no budget.
            missing_required = []
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

    def _should_use_structured_qp(self, baseline: dict[str, Any]) -> bool:
        if not self._enable_structured_qp:
            return False
        # Keep deterministic controls cheap and stable.
        if baseline["intent"] == "reset":
            return False
        if not baseline["normalized_query"]:
            return False
        return True

    def _get_structured_strategy(self) -> StructuredQPStrategy:
        if self._structured_strategy is None:
            self._structured_strategy = LLMStructuredQPStrategy()
        return self._structured_strategy

    @staticmethod
    def _coerce_context(context: StructuredQPContext | dict[str, Any] | None) -> StructuredQPContext | None:
        if context is None or isinstance(context, StructuredQPContext):
            return context
        return StructuredQPContext.model_validate(context)

    @staticmethod
    def _with_metadata(
        payload: dict[str, Any],
        *,
        qp_source: Literal["rule", "llm", "fallback"],
        confidence: float | None = None,
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        enriched = dict(payload)
        enriched["qp_source"] = qp_source
        enriched["confidence"] = confidence
        enriched["fallback_reason"] = fallback_reason
        return enriched

    def _merge_structured_result(
        self,
        query: str,
        baseline: dict[str, Any],
        result: StructuredQPResult,
    ) -> dict[str, Any]:
        normalized = baseline["normalized_query"]
        constraints = self._merge_constraints(
            self._constraints_from_dict(baseline["constraints"]),
            result,
        )
        presence = self._constraint_presence(constraints)
        missing_required = [key for key in HARD_REQUIRED_FIELDS if not presence.get(key, False)]
        intent = result.intent
        intent_detail = result.intent_detail or self._default_intent_detail(intent)
        recall_base = result.rewrite_query or result.recall_query or normalized
        recall_query = self._build_recall_query(self._normalize_query(recall_base), constraints)

        return QPOutput(
            intent=intent,
            intent_detail=intent_detail,
            normalized_query=normalized,
            recall_query=recall_query,
            constraints=constraints,
            constraint_presence=presence,
            missing_required=missing_required,
            rewrite_applied=bool(
                result.rewrite_query and result.rewrite_query.strip() != query.strip()
            ),
            qp_source="llm",
            confidence=result.confidence,
            fallback_reason=None,
        ).to_dict()

    @staticmethod
    def _constraints_from_dict(payload: dict[str, Any]) -> QPConstraints:
        return QPConstraints(
            destination_city=payload.get("destination_city"),
            days=payload.get("days"),
            budget=payload.get("budget"),
            traveler_type=payload.get("traveler_type"),
            preferences=list(payload.get("preferences") or []),
            pace=payload.get("pace"),
        )

    @staticmethod
    def _merge_constraints(base: QPConstraints, result: StructuredQPResult) -> QPConstraints:
        incoming = result.constraints
        preferences = list(dict.fromkeys([*base.preferences, *incoming.preferences]))
        return QPConstraints(
            destination_city=base.destination_city or incoming.destination_city,
            days=base.days if base.days is not None else incoming.days,
            budget=base.budget if base.budget is not None else incoming.budget,
            traveler_type=base.traveler_type or incoming.traveler_type,
            preferences=preferences,
            pace=base.pace or incoming.pace,
        )

    @staticmethod
    def _constraint_presence(constraints: QPConstraints) -> dict[str, bool]:
        return {
            "destination": bool(constraints.destination_city),
            "duration": constraints.days is not None,
            "budget": constraints.budget is not None,
            "travelers": bool(constraints.traveler_type),
        }

    @staticmethod
    def _default_intent_detail(intent: IntentType) -> IntentDetailType:
        mapping: dict[str, IntentDetailType] = {
            "create": "first_create",
            "edit": "edit_day",
            "qa": "qa_local",
            "reset": "reset_all",
            "chat": "general_chat",
        }
        return mapping[intent]

    # 标准化查询
    @staticmethod
    def _normalize_query(query: str) -> str:
        # Baseline rewrite: collapse whitespace for stable downstream matching.
        normalized = re.sub(r"\s+", " ", (query or "").strip())
        return normalized

    def _detect_intent(self, query: str) -> tuple[IntentType, IntentDetailType]:
        lower_q = query.lower()
        if any(self._contains_hint(query, lower_q, word) for word in QP_RULES.reset_hints) or bool(
            _ENGLISH_RESET_HINT_PATTERN.search(lower_q)
        ):
            return "reset", "reset_all"

        rule_edit_hint = any(self._contains_hint(query, lower_q, word) for word in QP_RULES.edit_hints)
        english_edit_hint = bool(_ENGLISH_EDIT_HINT_PATTERN.search(lower_q))
        has_edit_hint = rule_edit_hint or english_edit_hint
        has_day_ref = bool(QP_RULES.edit_day_pattern.search(lower_q))
        is_question = bool(QP_RULES.qa_question_pattern.search(query))
        has_travel_qa_topic = bool(_TRAVEL_QA_TOPIC_PATTERN.search(query))
        constraints = self._extract_constraints(query)
        is_full_create = (
            bool(constraints.destination_city)
            and constraints.days is not None
            and constraints.budget is not None
        )

        if any(self._contains_hint(query, lower_q, word) for word in QP_RULES.evidence_qa_hints) or bool(
            _ENGLISH_EVIDENCE_HINT_PATTERN.search(lower_q)
        ):
            return "qa", "qa_evidence"
        if is_question and has_travel_qa_topic and not has_edit_hint:
            return "qa", "qa_local"
        if has_edit_hint and not is_full_create:
            return "edit", "edit_day"
        if has_day_ref and not is_full_create:
            return "qa", "qa_local"

        has_any_travel_signal = (
            bool(constraints.destination_city)
            or constraints.days is not None
            or constraints.budget is not None
            or bool(constraints.traveler_type)
        )
        if not has_any_travel_signal:
            return "chat", "general_chat"
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
