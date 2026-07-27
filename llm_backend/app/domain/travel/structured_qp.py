from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import ServiceType, settings
from app.domain.travel.draft_builder import extract_budget


IntentName = Literal["create", "edit", "qa", "reset", "chat"]
IntentDetailName = Literal[
    "first_create",
    "edit_day",
    "qa_evidence",
    "qa_local",
    "reset_all",
    "general_chat",
]
EditConstraintName = Literal["indoor", "relaxed", "food", "culture"]
SlotName = Literal["上午", "下午", "晚上"]


class StructuredQPConstraints(BaseModel):
    destination_city: str | None = None
    days: int | None = Field(default=None, ge=1, le=30)
    budget: float | None = Field(default=None, ge=0)
    traveler_type: str | None = None
    preferences: list[str] = Field(default_factory=list)
    pace: Literal["relaxed", "intensive"] | None = None

    @field_validator("destination_city", "traveler_type", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("budget", mode="before")
    @classmethod
    def _normalize_budget(cls, value: Any) -> Any:
        if value is None or isinstance(value, int | float):
            return value
        if isinstance(value, str):
            parsed = extract_budget(f"预算{value}") or extract_budget(value)
            if parsed is not None:
                return parsed
            # Models often express a relative edit such as "lower" or
            # "cheaper". It is meaningful for intent routing but not a safe
            # numeric budget update, so preserve the edit and leave this slot
            # unresolved instead of rejecting the entire structured response.
            return None
        return value

    @field_validator("pace", mode="before")
    @classmethod
    def _normalize_pace(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized in {"relaxed", "slow", "easy", "light", "轻松", "慢节奏", "不赶", "别太累"}:
            return "relaxed"
        if normalized in {"intensive", "fast", "compact", "tight", "紧凑", "特种兵", "赶一点"}:
            return "intensive"
        return value


class StructuredQPResult(BaseModel):
    intent: IntentName
    intent_detail: IntentDetailName | None = None
    confidence: float = Field(ge=0, le=1)
    target_day: int | None = Field(default=None, ge=1, le=30)
    target_slot: SlotName | None = None
    edit_constraints: list[EditConstraintName] = Field(default_factory=list)
    constraints: StructuredQPConstraints = Field(default_factory=StructuredQPConstraints)
    missing_required: list[str] = Field(default_factory=list)
    recall_query: str | None = None
    rewrite_query: str | None = None
    reason: str | None = None

    @field_validator("target_slot", mode="before")
    @classmethod
    def _normalize_target_slot(cls, value: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        mapping = {
            "morning": "上午",
            "afternoon": "下午",
            "evening": "晚上",
            "night": "晚上",
            "早上": "上午",
            "中午": "下午",
            "夜晚": "晚上",
        }
        return mapping.get(normalized, value.strip() or None)

    @field_validator("edit_constraints", mode="before")
    @classmethod
    def _normalize_edit_constraints(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        aliases = {
            "室内": "indoor",
            "避雨": "indoor",
            "museum": "indoor",
            "轻松": "relaxed",
            "慢节奏": "relaxed",
            "美食": "food",
            "吃喝": "food",
            "文化": "culture",
            "人文": "culture",
        }
        allowed = {"indoor", "relaxed", "food", "culture"}
        normalized: list[str] = []
        for item in value:
            text = str(item or "").strip().lower()
            mapped = aliases.get(text, text)
            if mapped in allowed and mapped not in normalized:
                normalized.append(mapped)
        return normalized


class StructuredQPContext(BaseModel):
    has_itinerary: bool = False
    trip_profile: dict[str, Any] | None = None
    chat_summary: str | None = None
    last_user_query: str | None = None


STRUCTURED_QP_SYSTEM_PROMPT = """\
你是 TravelMind 的 Query Processing 模块，只负责理解用户输入并输出结构化 JSON。

边界：
- 只做意图识别、约束抽取、query 改写和缺字段判断。
- 不生成行程正文，不调用地图/搜索 Provider，不修改 itinerary。
- 当前 itinerary / trip_profile 是显式状态，只能作为理解上下文使用。
- 是否真正切换目的地由下游 ConversationDecisionService 结合当前状态最终决定；这里只抽取用户提到的 destination_city。
- 输出必须是纯 JSON，不要 markdown，不要解释性正文。

intent 只能是：
- create：首次创建或重新给出完整旅行需求
- edit：基于已有行程做增量修改
- qa：询问当前行程、证据、地点、交通、原因等
- reset：清空或重新开始当前会话
- chat：普通闲聊或非旅行对话

intent_detail 只能是：
- first_create, edit_day, qa_evidence, qa_local, reset_all, general_chat

输出 JSON schema：
{
  "intent": "create|edit|qa|reset|chat",
  "intent_detail": "first_create|edit_day|qa_evidence|qa_local|reset_all|general_chat",
  "confidence": 0.0,
  "target_day": null,
  "target_slot": "上午|下午|晚上|null",
  "edit_constraints": ["indoor|relaxed|food|culture"],
  "constraints": {
    "destination_city": null,
    "days": null,
    "budget": null,
    "traveler_type": null,
    "preferences": [],
    "pace": null
  },
  "missing_required": [],
  "recall_query": null,
  "rewrite_query": null,
  "reason": "不超过 40 字的判断依据"
}

当 intent=edit 时：
- 若修改某一天或某个时段，尽量给出 target_day；只在用户明确上午/下午/晚上时给出 target_slot。
- edit_constraints 只列会影响候选重规划的约束：indoor、relaxed、food、culture。
- 不要把具体 POI 名称当作 edit_constraints，也不要虚构 target_day/target_slot。
"""


class LLMStructuredQPStrategy:
    """LLM-backed Structured QP strategy with strict JSON validation."""

    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        model: str | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds or settings.STRUCTURED_QP_TIMEOUT_SECONDS
        self.model = model or settings.DEEPSEEK_MODEL
        self.client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
        )

    async def classify(
        self,
        query: str,
        *,
        context: StructuredQPContext | None = None,
    ) -> StructuredQPResult:
        if settings.AGENT_SERVICE != ServiceType.DEEPSEEK:
            raise RuntimeError("Structured QP currently supports DeepSeek-compatible chat API only")

        messages = [
            {"role": "system", "content": STRUCTURED_QP_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(query, context)},
        ]
        response = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
                stream=False,
            ),
            timeout=self.timeout_seconds,
        )
        content = response.choices[0].message.content or ""
        return self._parse_result(content)

    @staticmethod
    def _build_user_prompt(query: str, context: StructuredQPContext | None) -> str:
        ctx = context or StructuredQPContext()
        context_payload = {
            "has_itinerary": ctx.has_itinerary,
            "trip_profile": ctx.trip_profile,
            "chat_summary": ctx.chat_summary,
            "last_user_query": ctx.last_user_query,
        }
        return (
            "用户输入：\n"
            f"{query}\n\n"
            "当前显式状态 JSON：\n"
            f"{json.dumps(context_payload, ensure_ascii=False)}\n\n"
            "请只输出符合 schema 的 JSON。"
        )

    @staticmethod
    def _parse_result(content: str) -> StructuredQPResult:
        raw = content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise
            data = json.loads(match.group(0))
        try:
            return StructuredQPResult.model_validate(data)
        except ValidationError:
            raise
