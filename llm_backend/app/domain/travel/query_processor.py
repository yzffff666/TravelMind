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
from app.domain.travel.patch_engine import has_mutation_intent
from app.domain.travel.structured_qp import (
    LLMStructuredQPStrategy,
    StructuredQPContext,
    StructuredQPResult,
)

# 意图类型
IntentType = Literal["create", "edit", "qa", "reset", "chat"]
IntentDetailType = Literal["first_create", "edit_day", "qa_evidence", "qa_local", "reset_all", "general_chat"]
StructuredQPMode = Literal["off", "shadow", "selective"]
QPSafetyLevel = Literal["safe", "caution", "blocked"]

_ENGLISH_RESET_HINT_PATTERN = re.compile(
    r"\b(start over|begin again|clear (?:the\s+)?(?:trip|itinerary)|new trip)\b",
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
    r"recommendation|recommend|ref|reference|source|where|when|why|"
    r"busy|happens?|choose|chosen|better|how\s+long|how\s+do\s+i\s+get)",
    re.IGNORECASE,
)
_DAY_REFERENCE_PATTERN = re.compile(
    r"(?:第\s*(?:\d+|[一二两三四五六七八九十]+)\s*天|day\s*\d+)",
    re.IGNORECASE,
)
_SLOT_REFERENCE_PATTERN = re.compile(
    r"(?:上午|下午|晚上|早上|中午|夜晚|morning|afternoon|evening|night)",
    re.IGNORECASE,
)
_CONTEXTUAL_STATE_HINT_PATTERN = re.compile(
    r"(?:还是|保持|不要变|别变|酒店|住宿|节奏|轻松|赶|累|预算|偏好|"
    r"same|keep|hotel|stay|pace|relaxed|cheaper|budget|preference)",
    re.IGNORECASE,
)
_COMPLEX_CONTEXTUAL_EDIT_PATTERN = re.compile(
    r"(?:还是|保持|不要变|别变|住宿|酒店|same|keep|hotel|stay)",
    re.IGNORECASE,
)
_TRAVEL_CREATE_HINT_PATTERN = re.compile(
    r"(?:旅行|旅游|行程|出游|玩|去|攻略|trip|travel|visit|itinerary)",
    re.IGNORECASE,
)
_READONLY_MUTATION_QUESTION_PATTERN = re.compile(
    r"(?:了吗|有没有|有无|是否|是不是|是否已经|did\s+.*\?|is\s+.*\?)",
    re.IGNORECASE,
)
_MUTATION_REQUEST_PREFIX_PATTERN = re.compile(
    r"^(?:请|帮我|麻烦|能不能|可以|请问|please|can\s+you|could\s+you)",
    re.IGNORECASE,
)
_NEGATED_OR_PRESERVING_MUTATION_PATTERN = re.compile(
    r"(?:"
    r"(?:先|暂时)?(?:别|不要|不用|无需)(?:再|真的)?[^，。,.!?？]{0,10}"
    r"(?:改|修改|调整|替换|换|删除|新增)|"
    r"(?:保留|保持)[^，。,.!?？]{0,12}(?:安排|行程|修改|目的地|选择)|"
    r"(?:修改|调整)[^，。,.!?？]{0,8}(?:保留|保持)|"
    r"\b(?:do\s+not|don't|dont|never)\s+(?:change|modify|replace|switch)|"
    r"\bkeep\b[^.!?]{0,20}\b(?:trip|plan|itinerary|choice)\b"
    r")",
    re.IGNORECASE,
)
_TRAVEL_COMPARISON_OR_TRANSIT_PATTERN = re.compile(
    r"(?:"
    r"哪个(?:更)?(?:适合|好)|"
    r"怎么(?:走|去)|"
    r"\bbetter\s+than\b|"
    r"\bhow\s+do\s+i\s+get\s+from\b"
    r")",
    re.IGNORECASE,
)
_RESET_REPLAN_PATTERN = re.compile(
    r"(?:不要了|不需要了|算了).{0,8}(?:重新规划|重新来|从头规划)",
    re.IGNORECASE,
)
_READONLY_INFORMATION_REQUEST_PATTERN = re.compile(
    r"(?:"
    r"(?:看看|查看|告诉我|说明一下).{0,12}(?:预算|行程|安排|交通|地址|花费)|"
    r"\b(?:show|tell)\s+me\b.{0,24}\b(?:budget|plan|itinerary|schedule)\b"
    r")",
    re.IGNORECASE,
)
_CN_TARGET_DAY_PATTERN = re.compile(
    r"第\s*(\d+|[一二两三四五六七八九十]+)\s*天",
)
_ENGLISH_TARGET_DAY_PATTERN = re.compile(
    r"\bday\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_ENGLISH_ORDINAL_DAY_PATTERN = re.compile(
    r"\b(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
    r"(?:\s+day)?\b",
    re.IGNORECASE,
)
_DAY_WORD_VALUES = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "one": 1,
    "first": 1,
    "two": 2,
    "second": 2,
    "three": 3,
    "third": 3,
    "four": 4,
    "fourth": 4,
    "five": 5,
    "fifth": 5,
    "six": 6,
    "sixth": 6,
    "seven": 7,
    "seventh": 7,
    "eight": 8,
    "eighth": 8,
    "nine": 9,
    "ninth": 9,
    "ten": 10,
    "tenth": 10,
}
_TARGET_SLOT_VARIANTS = (
    ("上午", "上午"),
    ("早上", "上午"),
    ("morning", "上午"),
    ("下午", "下午"),
    ("afternoon", "下午"),
    ("晚上", "晚上"),
    ("夜晚", "晚上"),
    ("evening", "晚上"),
    ("night", "晚上"),
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
    structured_qp_mode: StructuredQPMode = "off"
    route_reason: str = "rule_baseline"
    safety_level: QPSafetyLevel = "safe"
    shadow_intent: IntentType | None = None
    shadow_confidence: float | None = None
    target_day: int | None = None
    target_slot: str | None = None
    edit_constraints: list[str] = field(default_factory=list)

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
        structured_qp_mode: StructuredQPMode | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        self._structured_strategy = structured_strategy
        self._structured_qp_mode = self._resolve_structured_qp_mode(
            enable_structured_qp=enable_structured_qp,
            structured_qp_mode=structured_qp_mode,
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
        structured_context = self._coerce_context(context)
        route_reason = self._route_reason(
            query=query,
            baseline=baseline,
            context=structured_context,
        )
        if route_reason is None:
            return self._with_metadata(
                baseline,
                qp_source="rule",
                structured_qp_mode=self._structured_qp_mode,
                route_reason="rule_fast_path",
            )

        if self._structured_qp_mode == "off":
            return self._with_metadata(
                baseline,
                qp_source="rule",
                structured_qp_mode="off",
                route_reason=f"off:{route_reason}",
            )

        try:
            result = await self._get_structured_strategy().classify(
                query,
                context=structured_context,
            )
        except Exception as exc:
            return self._with_metadata(
                baseline,
                qp_source="rule" if self._structured_qp_mode == "shadow" else "fallback",
                structured_qp_mode=self._structured_qp_mode,
                route_reason=f"{self._structured_qp_mode}:{route_reason}",
                safety_level="caution",
                fallback_reason=f"{self._structured_qp_mode}_exception:{type(exc).__name__}: {exc}",
            )

        safety_failure = self._validate_structured_result(
            query=query,
            baseline=baseline,
            result=result,
            context=structured_context,
        )
        if self._structured_qp_mode == "shadow":
            return self._with_metadata(
                baseline,
                qp_source="rule",
                confidence=result.confidence,
                structured_qp_mode="shadow",
                route_reason=f"shadow:{route_reason}",
                safety_level="caution" if safety_failure else "safe",
                fallback_reason=safety_failure,
                shadow_intent=result.intent,
                shadow_confidence=result.confidence,
            )

        if result.confidence < self._confidence_threshold:
            return self._with_metadata(
                baseline,
                qp_source="fallback",
                confidence=result.confidence,
                structured_qp_mode="selective",
                route_reason=f"selective:{route_reason}",
                safety_level="caution",
                fallback_reason="low_confidence",
            )

        if safety_failure:
            return self._with_metadata(
                baseline,
                qp_source="fallback",
                confidence=result.confidence,
                structured_qp_mode="selective",
                route_reason=f"selective:{route_reason}",
                safety_level="blocked",
                fallback_reason=safety_failure,
            )

        return self._merge_structured_result(
            query,
            baseline,
            result,
            structured_qp_mode="selective",
            route_reason=f"selective:{route_reason}",
        )

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
        target_day = self._extract_target_day(normalized)
        target_slot = self._extract_target_slot(normalized)
        if intent in {"qa", "edit"} and target_day is not None:
            # "第三天" describes the target scope, not a new trip duration.
            constraints.days = None
            # A local edit such as "改成室内活动" must not reinterpret the
            # activity phrase as a destination replacement.
            if intent == "edit":
                constraints.destination_city = None
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
            target_day=target_day,
            target_slot=target_slot,
        ).to_dict()

    @staticmethod
    def _resolve_structured_qp_mode(
        *,
        enable_structured_qp: bool | None,
        structured_qp_mode: StructuredQPMode | None,
    ) -> StructuredQPMode:
        if structured_qp_mode is not None:
            return structured_qp_mode
        if enable_structured_qp is not None:
            return "selective" if enable_structured_qp else "off"
        if settings.STRUCTURED_QP_MODE != "off":
            return settings.STRUCTURED_QP_MODE
        return "selective" if settings.ENABLE_STRUCTURED_QP else "off"

    def _route_reason(
        self,
        *,
        query: str,
        baseline: dict[str, Any],
        context: StructuredQPContext | None,
    ) -> str | None:
        normalized = baseline["normalized_query"]
        intent = baseline["intent"]
        has_itinerary = bool(context and context.has_itinerary)
        if not normalized or intent == "reset":
            return None
        if intent == "qa" and not has_mutation_intent(query):
            return None
        if intent == "chat" and not (has_itinerary and _CONTEXTUAL_STATE_HINT_PATTERN.search(query)):
            return None
        if intent == "edit":
            if not has_itinerary:
                return None
            if _DAY_REFERENCE_PATTERN.search(query) and has_mutation_intent(query) and not (
                _COMPLEX_CONTEXTUAL_EDIT_PATTERN.search(query)
            ):
                return None
            return "contextual_edit"
        if intent == "create":
            constraints = baseline["constraints"]
            complete = bool(
                constraints.get("destination_city")
                and constraints.get("days") is not None
                and constraints.get("budget") is not None
            )
            if complete:
                return None
            if constraints.get("days") is not None and constraints.get("budget") is not None:
                return "missing_destination"
            if has_itinerary and _CONTEXTUAL_STATE_HINT_PATTERN.search(query):
                return "contextual_state"
            return None
        if has_itinerary and _CONTEXTUAL_STATE_HINT_PATTERN.search(query):
            return "contextual_state"
        if _TRAVEL_CREATE_HINT_PATTERN.search(query):
            return "weak_travel_signal"
        return None

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
        structured_qp_mode: StructuredQPMode = "off",
        route_reason: str = "rule_baseline",
        safety_level: QPSafetyLevel = "safe",
        shadow_intent: IntentType | None = None,
        shadow_confidence: float | None = None,
    ) -> dict[str, Any]:
        enriched = dict(payload)
        enriched["qp_source"] = qp_source
        enriched["confidence"] = confidence
        enriched["fallback_reason"] = fallback_reason
        enriched["structured_qp_mode"] = structured_qp_mode
        enriched["route_reason"] = route_reason
        enriched["safety_level"] = safety_level
        enriched["shadow_intent"] = shadow_intent
        enriched["shadow_confidence"] = shadow_confidence
        return enriched

    def _merge_structured_result(
        self,
        query: str,
        baseline: dict[str, Any],
        result: StructuredQPResult,
        *,
        structured_qp_mode: StructuredQPMode,
        route_reason: str,
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
        if intent != "create":
            missing_required = []
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
            structured_qp_mode=structured_qp_mode,
            route_reason=route_reason,
            safety_level="safe",
            target_day=result.target_day,
            target_slot=result.target_slot,
            edit_constraints=list(result.edit_constraints),
        ).to_dict()

    @staticmethod
    def _validate_structured_result(
        *,
        query: str,
        baseline: dict[str, Any],
        result: StructuredQPResult,
        context: StructuredQPContext | None,
    ) -> str | None:
        has_itinerary = bool(context and context.has_itinerary)
        if result.intent == "reset":
            return "structured_reset_disallowed"
        if baseline["intent"] == "qa" and not has_mutation_intent(query) and result.intent != "qa":
            return "readonly_query_reclassified"
        if result.intent == "edit" and not has_mutation_intent(query):
            return "edit_without_explicit_mutation"
        if result.intent == "edit" and not has_itinerary:
            return "edit_without_itinerary"
        if result.intent == "create" and has_itinerary and has_mutation_intent(query):
            return "create_over_existing_itinerary"
        if result.target_day is not None and result.intent != "edit":
            return "target_day_without_edit"
        return None

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
        ) or bool(_RESET_REPLAN_PATTERN.search(query)):
            return "reset", "reset_all"

        rule_edit_hint = any(self._contains_hint(query, lower_q, word) for word in QP_RULES.edit_hints)
        english_edit_hint = bool(_ENGLISH_EDIT_HINT_PATTERN.search(lower_q))
        has_edit_hint = rule_edit_hint or english_edit_hint
        has_day_ref = self._extract_target_day(query) is not None
        is_question = bool(QP_RULES.qa_question_pattern.search(query))
        has_travel_qa_topic = bool(_TRAVEL_QA_TOPIC_PATTERN.search(query))
        constraints = self._extract_constraints(query)
        is_full_create = (
            bool(constraints.destination_city)
            and constraints.days is not None
            and constraints.budget is not None
        )

        if _NEGATED_OR_PRESERVING_MUTATION_PATTERN.search(query):
            if is_question and (
                has_travel_qa_topic
                or _TRAVEL_COMPARISON_OR_TRANSIT_PATTERN.search(query)
            ):
                return "qa", "qa_local"
            return "chat", "general_chat"
        if any(self._contains_hint(query, lower_q, word) for word in QP_RULES.evidence_qa_hints) or bool(
            _ENGLISH_EVIDENCE_HINT_PATTERN.search(lower_q)
        ):
            return "qa", "qa_evidence"
        if _READONLY_INFORMATION_REQUEST_PATTERN.search(query):
            return "qa", "qa_local"
        if is_question and _TRAVEL_COMPARISON_OR_TRANSIT_PATTERN.search(query):
            return "qa", "qa_local"
        if is_question and has_travel_qa_topic and (
            not has_edit_hint or self._is_readonly_mutation_question(query)
        ):
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
    def _extract_target_day(query: str) -> int | None:
        for pattern in (
            _CN_TARGET_DAY_PATTERN,
            _ENGLISH_TARGET_DAY_PATTERN,
            _ENGLISH_ORDINAL_DAY_PATTERN,
        ):
            match = pattern.search(query)
            if not match:
                continue
            raw = match.group(1).lower()
            if raw.isdigit():
                return int(raw)
            if raw in _DAY_WORD_VALUES:
                return _DAY_WORD_VALUES[raw]
            if len(raw) == 2 and raw.startswith("十"):
                return 10 + _DAY_WORD_VALUES.get(raw[1], 0)
            if len(raw) == 2 and raw.endswith("十"):
                return _DAY_WORD_VALUES.get(raw[0], 1) * 10
        return None

    @staticmethod
    def _extract_target_slot(query: str) -> str | None:
        lowered = query.lower()
        for variant, canonical in _TARGET_SLOT_VARIANTS:
            if variant in query or (variant.isascii() and variant in lowered):
                return canonical
        return None

    @staticmethod
    def _contains_hint(raw_query: str, lower_query: str, hint: str) -> bool:
        """Chinese hints use substring; ASCII hints use whole-word match."""
        if hint.isascii():
            return bool(re.search(rf"\b{re.escape(hint.lower())}\b", lower_query))
        return hint in raw_query

    @staticmethod
    def _is_readonly_mutation_question(query: str) -> bool:
        """Distinguish "has day 2 been changed?" from a change request."""
        return bool(
            _READONLY_MUTATION_QUESTION_PATTERN.search(query)
            and not _MUTATION_REQUEST_PREFIX_PATTERN.search(query.strip())
        )

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
