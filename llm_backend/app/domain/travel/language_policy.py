"""Deterministic response-language policy and localized backend copy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ResponseLanguage = Literal["en", "zh-CN"]
DecisionSource = Literal[
    "explicit_override",
    "query_signal",
    "conversation_state",
    "ui_locale",
    "default",
]

_HAN_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_ENGLISH_WORD_PATTERN = re.compile(r"\b[A-Za-z]+(?:['’][A-Za-z]+)?\b")
_ENGLISH_OVERRIDE = re.compile(
    r"\b(?:reply|respond|answer|speak|write|use)\b.{0,24}\benglish\b"
    r"|\bin\s+english\b",
    re.IGNORECASE,
)
_CHINESE_OVERRIDE = re.compile(
    r"\b(?:reply|respond|answer|speak|write|use)\b.{0,24}\bchinese\b"
    r"|\bin\s+chinese\b",
    re.IGNORECASE,
)
_ZH_OVERRIDE = re.compile(r"(?:请)?(?:用|说|改用|切换到)?中文(?:回答|回复|交流)?")
_ZH_TO_EN_OVERRIDE = re.compile(
    r"(?:请)?(?:用|说|改用|切换到)?英文(?:回答|回复|交流)?"
)

_AMBIGUOUS_ACKS = {
    "ok",
    "okay",
    "yes",
    "sure",
    "fine",
    "either is fine",
    "anything is fine",
    "up to you",
    "you decide",
    "好的",
    "好",
    "可以",
    "都可以",
    "都行",
    "随便",
    "你决定",
    "你安排",
    "没问题",
}

_COPY: dict[ResponseLanguage, dict[str, str]] = {
    "en": {
        "clarification_hard_only": (
            "To build a workable itinerary, please provide: {hard_text}."
        ),
        "clarification_hard_and_soft": (
            "To build a workable itinerary, please provide: {hard_text}. "
            "It would also help to provide: {soft_text} (optional)."
        ),
        "missing_itinerary": (
            "There is no itinerary to edit yet. Please provide a destination, "
            "trip length, and budget first."
        ),
        "reset_done": (
            "The itinerary state for this conversation has been reset. "
            "You can enter a new travel request."
        ),
        "draft_failed": "Itinerary generation failed. Please try again later.",
        "draft_missing_fields": (
            "I could not generate a structured itinerary. Please provide a "
            "destination, trip length, and budget, then try again."
        ),
        "draft_missing_p0": (
            "To build a structured itinerary, please provide: {missing_fields}."
        ),
        "edit_not_confirmed": (
            "I cannot confirm that you want to edit the itinerary. Ask a question "
            "to keep it unchanged, or say clearly which day or time slot to edit."
        ),
        "edit_target_missing": (
            "Please specify which day or time slot you want to change."
        ),
        "edit_failed": "The edit could not be applied. Please rephrase the change.",
        "edit_replan_unverified": (
            "The requested edit did not produce a verified replacement, so the "
            "original itinerary was preserved. {details}"
        ),
        "edit_replan_details": "No verified replacement candidates were available.",
        "edit_provider_failed": (
            "Candidate verification for this edit failed, so the original "
            "itinerary was preserved. Please try again later."
        ),
        "edit_exception": "The edit failed unexpectedly: {details}",
        "edit_success": "Updated {days}. Other days were preserved.",
        "edit_success_generic": "The itinerary update was applied.",
        "edit_success_item": "Updated {day} based on the requested constraints.",
        "candidate_insufficient": (
            "There are not enough verified local candidates to publish a safe "
            "itinerary. Please refine the area or try again later."
        ),
        "chat_fallback": (
            "Hello! I am the TravelMind travel assistant. How can I help?"
        ),
        "guided_budget": (
            "Let us set the budget first. Would you prefer about 3,000, 5,000, "
            "or 8,000 CNY?"
        ),
        "guided_fallback": (
            "Thanks. I still need one detail: {missing_text}. Could you provide it?"
        ),
        "duplicate_request": (
            "An identical request is already being processed. Please wait for "
            "the current result before continuing."
        ),
    },
    "zh-CN": {
        "clarification_hard_only": "为保证行程可执行，请先补充：{hard_text}。",
        "clarification_hard_and_soft": (
            "为保证行程可执行，请先补充：{hard_text}。"
            "另外建议补充：{soft_text}（可选，不填也能先出草案）。"
        ),
        "missing_itinerary": (
            "当前会话还没有可编辑的行程，请先描述目的地、天数和预算生成草案。"
        ),
        "reset_done": (
            "已为当前会话重置行程状态，你可以重新输入新的出行需求。"
        ),
        "draft_failed": "草案生成失败，请稍后再试。",
        "draft_missing_fields": (
            "未能生成结构化草案，请补充目的地、天数和预算后重试。"
        ),
        "draft_missing_p0": "为了生成结构化行程草案，请补充：{missing_fields}。",
        "edit_not_confirmed": (
            "我还不能确认你是要修改行程。如果只是询问，我会按当前行程回答；"
            "如果要修改，请明确说明要修改的天数或时段。"
        ),
        "edit_target_missing": (
            "未指定修改哪一天或时段，请说明第N天和上午、下午或晚上。"
        ),
        "edit_failed": "编辑失败，请重新描述修改内容。",
        "edit_replan_unverified": (
            "这次修改未生成可验证的候选行程，已保留原行程。{details}"
        ),
        "edit_replan_details": "候选不足，未生成可验证的局部行程。",
        "edit_provider_failed": (
            "这次修改未能完成候选验证，已保留原行程，请稍后重试。"
        ),
        "edit_exception": "编辑处理异常：{details}",
        "edit_success": "已修改{days}，其他日期保持不变。",
        "edit_success_generic": "行程修改已应用。",
        "edit_success_item": "已按要求修改{day}。",
        "candidate_insufficient": (
            "可验证的本地候选不足，为避免发布不可靠行程，请补充更具体的区域或稍后重试。"
        ),
        "chat_fallback": (
            "你好！我是 TravelMind 旅行助手，有什么我可以帮你的吗？"
        ),
        "guided_budget": (
            "可以的，那我们先定预算区间吧：比如3000、5000或8000元，你更倾向哪个？"
        ),
        "guided_fallback": "收到！还需要了解一下：{missing_text}，方便告诉我吗？",
        "duplicate_request": "相同请求正在处理中，请稍等当前结果返回后再继续。",
    },
}


@dataclass(frozen=True)
class LanguageDecision:
    language: ResponseLanguage
    source: DecisionSource
    changed: bool


def normalize_ui_locale(value: str | None) -> ResponseLanguage | None:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"en", "en-us", "en-gb"}:
        return "en"
    if normalized in {"zh", "zh-cn", "zh-hans"}:
        return "zh-CN"
    return None


def _normalized_ack(query: str) -> str:
    return re.sub(r"[.!?。！？,\s]+", " ", query.strip().lower()).strip()


def _explicit_language(query: str) -> ResponseLanguage | None:
    if _ENGLISH_OVERRIDE.search(query) or _ZH_TO_EN_OVERRIDE.search(query):
        return "en"
    if _CHINESE_OVERRIDE.search(query) or _ZH_OVERRIDE.search(query):
        return "zh-CN"
    return None


def resolve_response_language(
    query: str,
    *,
    current_language: str | None = None,
    ui_locale: str | None = None,
) -> LanguageDecision:
    normalized_current = normalize_ui_locale(current_language)
    explicit = _explicit_language(query or "")
    if explicit:
        return LanguageDecision(
            language=explicit,
            source="explicit_override",
            changed=normalized_current is not None and normalized_current != explicit,
        )

    normalized_query = _normalized_ack(query or "")
    if normalized_query not in _AMBIGUOUS_ACKS:
        if _HAN_PATTERN.search(query or ""):
            language: ResponseLanguage = "zh-CN"
            return LanguageDecision(
                language=language,
                source="query_signal",
                changed=(
                    normalized_current is not None
                    and normalized_current != language
                ),
            )
        if len(_ENGLISH_WORD_PATTERN.findall(query or "")) >= 2:
            language = "en"
            return LanguageDecision(
                language=language,
                source="query_signal",
                changed=(
                    normalized_current is not None
                    and normalized_current != language
                ),
            )

    if normalized_current:
        return LanguageDecision(
            language=normalized_current,
            source="conversation_state",
            changed=False,
        )

    normalized_locale = normalize_ui_locale(ui_locale)
    if normalized_locale:
        return LanguageDecision(
            language=normalized_locale,
            source="ui_locale",
            changed=False,
        )

    return LanguageDecision(language="en", source="default", changed=False)


def localized_text(
    key: str,
    language: str | None,
    **values: object,
) -> str:
    resolved_language = normalize_ui_locale(language) or "en"
    template = _COPY.get(resolved_language, _COPY["en"]).get(key)
    if template is None:
        template = _COPY["en"].get(key, key)
    return template.format(**values)
