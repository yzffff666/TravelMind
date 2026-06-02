import os
import time
from datetime import datetime
from hashlib import md5
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from app.core.config import settings

from app.core.database import AsyncSessionLocal
from app.core.logger import get_logger
from app.domain.travel.patch_engine import apply_patch, has_mutation_intent, parse_edit_ops
from app.domain.travel.sse_envelope import (
    build_data_line,
    build_event_envelope,
    build_event_line,
)
from app.domain.travel.query_processor import TravelQueryProcessor
from app.lg_agent.travel_draft_graph import (
    _apply_city_center_fallback,
    _detect_response_language,
    travel_draft_graph,
)
from app.lg_agent.utils import new_uuid
from app.models.user import User
from app.services.conversation_service import ConversationService
from app.services.coverage_tracker import CoverageTracker
from app.services.deepseek_service import DeepseekService
from app.services.location_backfill_service import LocationBackfillService
from app.services.travel_clarification_service import TravelClarificationService
from app.schemas.itinerary_v1 import ItineraryV1

router = APIRouter()
logger = get_logger(service="travel_api")
# 澄清服务实例：用于在进入主规划链路前做“硬门槛缺失即追问”拦截。
clarification_service = TravelClarificationService()
# QP baseline：统一上游 query 与下游输入语义（T-M2-000a）。
query_processor = TravelQueryProcessor()
edit_backfill_service = LocationBackfillService(
    max_slots_per_request=3,
    max_variants_per_place=3,
    provider_timeout_seconds=1.5,
    total_budget_seconds=3.0,
)
_active_request_fingerprints: dict[str, float] = {}


def _request_fingerprint(*, user_id: int, conversation_id: str | None, query: str) -> str:
    scope = conversation_id or "new"
    normalized = " ".join((query or "").strip().lower().split())
    raw = f"{user_id}|{scope}|{normalized}"
    return md5(raw.encode("utf-8")).hexdigest()


def _try_acquire_request_fingerprint(fingerprint: str) -> bool:
    now = time.monotonic()
    ttl = max(0.1, settings.TRAVEL_REQUEST_DEDUPE_TTL_SECONDS)
    expired = [key for key, ts in _active_request_fingerprints.items() if now - ts >= ttl]
    for key in expired:
        _active_request_fingerprints.pop(key, None)

    if fingerprint in _active_request_fingerprints:
        return False
    _active_request_fingerprints[fingerprint] = now
    return True


def _release_request_fingerprint(fingerprint: str | None) -> None:
    if fingerprint:
        _active_request_fingerprints.pop(fingerprint, None)


async def _guard_stream(stream, fingerprint: str):
    try:
        async for line in stream:
            yield line
    finally:
        _release_request_fingerprint(fingerprint)


def _guard_response(response: StreamingResponse, fingerprint: str | None) -> StreamingResponse:
    if fingerprint:
        response.body_iterator = _guard_stream(response.body_iterator, fingerprint)
    return response


def _build_duplicate_request_response(*, request_id: str, conversation_id: str) -> StreamingResponse:
    return StreamingResponse(
        _stream_intent_text_response(
            request_id=request_id,
            conversation_id=conversation_id,
            intent="chat",
            intent_detail="general_chat",
            text="相同请求正在处理中，请稍等当前结果返回后再继续。",
        ),
        media_type="text/event-stream",
    )


async def _build_qp_context(conversation_id: str) -> dict | None:
    if not settings.ENABLE_STRUCTURED_QP:
        return None
    state = await ConversationService.get_travel_conversation_state(conversation_id)
    if not state:
        return None
    return {
        "has_itinerary": bool(state.get("current_itinerary")),
        "trip_profile": state.get("trip_profile"),
        "chat_summary": state.get("chat_summary"),
        "last_user_query": state.get("last_user_query"),
    }


async def _process_qp(query: str, conversation_id: str) -> dict:
    return await query_processor.process_async(
        query,
        context=await _build_qp_context(conversation_id),
    )

# 构建SSE行
def _build_sse_line(payload: object) -> str:
    return build_data_line(payload)

# 流式意图路由事件
async def _stream_intent_routed_event(
    *,
    request_id: str,
    conversation_id: str,
    intent: str,
    intent_detail: str,
):
    # 构建事件行
    yield build_event_line(
        "intent_routed",
        # 构建事件包裹
        build_event_envelope(
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=None,
            payload={
                "intent": intent,
                "intent_detail": intent_detail,
            },
        ),
    )

# 流式意图文本响应
async def _stream_intent_text_response(
    *,
    request_id: str,
    conversation_id: str,
    intent: str,
    intent_detail: str,
    text: str,
    event_name: str = "final_text",
    payload_extra: dict | None = None,
):
    # 流式意图路由事件
    async for line in _stream_intent_routed_event(
        request_id=request_id,
        conversation_id=conversation_id,
        intent=intent,
        intent_detail=intent_detail,
    ):
        yield line
    # 构建事件行
    yield build_event_line(
        # 构建事件包裹
        event_name,
        build_event_envelope(
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=None,
            payload={"text": text, **(payload_extra or {})},
        ),
    )
    yield _build_sse_line(text)


_chat_llm = DeepseekService()

_CHAT_SYSTEM_PROMPT = (
    "你是 TravelMind 旅行助手。你可以和用户自由聊天，回答各种问题。"
    "当话题与旅行相关时，自然地引导用户提供目的地、天数和预算，"
    "以便为他们生成行程规划。回答简洁友好，不超过 300 字。"
)

_SUMMARIZE_PROMPT = (
    "请将以下对话历史压缩为一段简洁的摘要（不超过 150 字），"
    "保留用户的关键偏好、已确认的约束和重要上下文信息。\n\n"
)

_GUIDED_SYSTEM_PROMPT = (
    "你是 TravelMind 旅行顾问，正在通过自然对话帮助用户规划旅行。\n"
    "当前已知信息：{known}\n"
    "还需要了解：{missing}\n\n"
    "规则：\n"
    "1. 先对用户的选择表示认同和兴趣，展现你对目的地或旅行的了解\n"
    "2. 每次只问一个问题，优先问最重要的缺失信息\n"
    "3. 像专业旅行顾问和朋友一样聊天，不要用模板化语言\n"
    "4. 给出实用建议帮助用户决策（如推荐天数范围、预算参考）\n"
    "5. 回答不超过80字，简洁有温度\n"
    "6. 用户的回复通常是在回应你上一个问题，请结合对话上下文理解意图\n"
    "7. 如果用户回复模糊（如'少一点''差不多''看情况'），引导用户给出具体数值\n"
    "8. 严格基于'当前已知信息'回应，不要遗忘已确认的目的地或天数\n"
)

RECENT_WINDOW = 6  # keep last 6 turns raw (12 messages)
_AMBIGUOUS_BUDGET_PHRASES = (
    "少一点", "低一点", "便宜点", "省一点", "差不多", "看情况",
    "都可以", "都行", "都好", "随便", "无所谓", "可以", "好的", "好",
)

async def _ensure_user_exists(user_id: int) -> None:
    """Fail fast for invalid user_id to avoid FK 500 in conversation state upsert."""
    async with AsyncSessionLocal() as db:
        exists = await db.scalar(select(User.id).where(User.id == user_id))
    if exists is None:
        logger.warning(f"Invalid user_id in travel API request: {user_id}")
        raise HTTPException(status_code=401, detail="用户不存在或登录已失效，请重新登录")


def _needs_budget_clarification_hint(query: str, missing_text: str) -> bool:
    """Return True when we should deterministically re-ask budget range.

    This avoids LLM drift where budget-only missing state can accidentally
    trigger a question about days/destination on vague replies.
    """
    budget_only_missing = (
        "预算" in missing_text
        and "几天" not in missing_text
        and "哪里" not in missing_text
        and "目的地" not in missing_text
    )
    if not budget_only_missing:
        return False
    q = (query or "").strip()
    return any(phrase in q for phrase in _AMBIGUOUS_BUDGET_PHRASES)


def _build_system_prompt(summary: str, itinerary: dict | None) -> str:
    parts = [_CHAT_SYSTEM_PROMPT]
    if summary:
        parts.append(f"\n[之前的对话摘要] {summary}")
    if itinerary:
        profile = itinerary.get("trip_profile", {})
        dest = profile.get("destination_city", "")
        days_count = len(itinerary.get("days", []))
        if dest:
            parts.append(
                f"\n[当前行程] 用户已有一个 {dest} {days_count}天 的行程规划，"
                "回答时可以参考该行程。"
            )
    return "".join(parts)


async def _compress_old_history(conversation_id: str, full_history: list[dict]) -> None:
    old_part = full_history[:-(RECENT_WINDOW * 2)]
    recent_part = full_history[-(RECENT_WINDOW * 2):]

    old_text = "\n".join(f"{m['role']}: {m['content']}" for m in old_part)
    try:
        summary = await _chat_llm.generate([
            {"role": "system", "content": _SUMMARIZE_PROMPT},
            {"role": "user", "content": old_text},
        ])
    except Exception as e:
        logger.warning(f"History compression failed, skipping: {e}")
        return
    await ConversationService.update_chat_summary(conversation_id, summary, recent_part)


async def _generate_chat_response(query: str, conversation_id: str) -> str:
    state = await ConversationService.get_travel_conversation_state(conversation_id)
    history: list[dict] = (state.get("chat_history") or []) if state else []
    summary: str = (state.get("chat_summary") or "") if state else ""
    itinerary: dict | None = (state.get("current_itinerary") or None) if state else None

    messages: list[dict] = [{"role": "system", "content": _build_system_prompt(summary, itinerary)}]
    recent = history[-(RECENT_WINDOW * 2):] if len(history) > RECENT_WINDOW * 2 else history
    messages.extend(recent)
    messages.append({"role": "user", "content": query})

    try:
        reply = await _chat_llm.generate(messages)
    except Exception as e:
        logger.error(f"Chat LLM call failed: {e}", exc_info=True)
        reply = "你好！我是 TravelMind 旅行助手，有什么我可以帮你的吗？"

    await ConversationService.append_chat_history(conversation_id, query, reply)

    updated_history = history + [
        {"role": "user", "content": query},
        {"role": "assistant", "content": reply},
    ]
    if len(updated_history) > RECENT_WINDOW * 2:
        await _compress_old_history(conversation_id, updated_history)

    return reply


async def _generate_guided_response(
    query: str,
    conversation_id: str,
    known_text: str,
    missing_text: str,
) -> str:
    """Use LLM to generate a natural follow-up question for missing constraints."""
    if _needs_budget_clarification_hint(query=query, missing_text=missing_text):
        # Keep one-question rhythm and ask for concrete budget values.
        return "可以的，那我们先定预算区间吧：比如3000、5000或8000元，你更倾向哪个？"

    state = await ConversationService.get_travel_conversation_state(conversation_id)
    history: list[dict] = (state.get("chat_history") or []) if state else []

    system_prompt = _GUIDED_SYSTEM_PROMPT.format(known=known_text, missing=missing_text)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    recent = history[-(RECENT_WINDOW * 2):] if len(history) > RECENT_WINDOW * 2 else history
    messages.extend(recent)
    messages.append({"role": "user", "content": query})

    try:
        reply = await _chat_llm.generate(messages)
    except Exception as e:
        logger.error(f"Guided LLM call failed: {e}", exc_info=True)
        reply = f"收到！还需要了解一下：{missing_text}，方便告诉我吗？"

    await ConversationService.append_chat_history(conversation_id, query, reply)
    return reply


# 流式澄清事件
async def _stream_clarification_events(
    *,
    request_id: str,
    conversation_id: str,
    missing_hard: list[str],
    missing_soft: list[str],
):
    # 构建澄清负载
    clarification_payload = clarification_service.build_clarification_payload(
        missing_hard=missing_hard,
        missing_soft=missing_soft,
    )
    # 阶段
    stage = clarification_payload["stage"]
    # 消息
    message = clarification_payload["message"]

    # 构建事件行
    yield build_event_line(
        "stage_start",
        build_event_envelope(
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=None,
            payload={"stage": stage},
        ),
    )
    # 构建事件行
    yield build_event_line(
        "stage_progress",
        build_event_envelope(
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=None,
            payload=clarification_payload,
        ),
    )
    # Text fallback for old clients.
    # 构建SSE行
    yield _build_sse_line(message)


# 流式最小行程草案
async def _stream_minimal_itinerary(
    *,
    query_text: str,
    original_query: str | None = None,
    thread_config: dict,
    conversation_id: str,
    request_id: str,
    user_id: int | None = None,
):
    # --- stage_start(draft_plan) → 前端显示骨架屏 ---
    yield build_event_line(
        "stage_start",
        build_event_envelope(
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=None,
            payload={"stage": "draft_plan"},
        ),
    )

    try:
        result = await travel_draft_graph.ainvoke(
            input={"query": query_text, "original_query": original_query or query_text},
            config=thread_config,
        )
        final_itinerary = result.get("final_itinerary")
        explanation = result.get("explanation")
        final_text = result.get("final_text")
        perf = result.get("perf", {})

        if not final_itinerary:
            fallback_text = final_text or "未能生成结构化草案，请补充目的地、天数和预算后重试。"
            yield build_event_line(
                "final_text",
                build_event_envelope(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=None,
                    payload={"text": fallback_text},
                ),
            )
            yield _build_sse_line(fallback_text)
            return

        # --- pipeline_complete → notify frontend recall phase is done ---
        evidence_items = final_itinerary.get("evidence", [])
        candidate_count = len(evidence_items)
        yield build_event_line(
            "pipeline_complete",
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=final_itinerary.get("revision_id"),
                payload={
                    "candidate_count": candidate_count,
                    "recall_ms": perf.get("recall_ms"),
                },
            ),
        )

        # --- tool_result(evidence_batch) → 前端填充证据标记 ---
        if evidence_items:
            yield build_event_line(
                "tool_result",
                build_event_envelope(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=final_itinerary.get("revision_id"),
                    payload={
                        "tool": "evidence_batch",
                        "evidence_count": len(evidence_items),
                        "evidence": evidence_items,
                    },
                ),
            )

        # --- day_ready → progressive day-by-day rendering ---
        days = final_itinerary.get("days", [])
        for day in days:
            yield build_event_line(
                "day_ready",
                build_event_envelope(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=final_itinerary.get("revision_id"),
                    payload={"day": day},
                ),
            )

        # --- stage_progress(validation_summary) → 前端显示校验进度 ---
        validation = final_itinerary.get("validation", {})
        if validation.get("coverage_score") is not None or validation.get("assumptions"):
            yield build_event_line(
                "stage_progress",
                build_event_envelope(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=final_itinerary.get("revision_id"),
                    payload={
                        "stage": "validation_summary",
                        "coverage_score": validation.get("coverage_score"),
                        "assumptions": validation.get("assumptions", []),
                        "conflicts": validation.get("conflicts", []),
                    },
                ),
            )

        # --- final_itinerary → 前端完整渲染 ---
        yield build_event_line(
            "final_itinerary",
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=final_itinerary.get("revision_id"),
                payload={
                    "itinerary": final_itinerary,
                    "explanation": explanation or "",
                    "perf": perf,
                },
            ),
        )
        try:
            await ConversationService.upsert_travel_conversation_state(
                conversation_id=conversation_id,
                user_id=user_id,
                current_revision_id=final_itinerary.get("revision_id"),
                trip_profile=final_itinerary.get("trip_profile"),
                current_itinerary=final_itinerary,
                last_user_query=query_text,
            )
        except Exception as persist_error:
            logger.error(
                f"Persist travel conversation state failed: {str(persist_error)}",
                exc_info=True,
            )
        if explanation:
            yield _build_sse_line(explanation)
    except Exception as e:
        logger.error(f"Generate travel draft failed: {str(e)}", exc_info=True)
        fallback_text = "草案生成失败，请稍后再试。"
        yield build_event_line(
            "error",
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=None,
                payload={"text": fallback_text},
            ),
        )
        yield _build_sse_line(fallback_text)


def _answer_itinerary_qa(
    query: str,
    itinerary: dict,
    response_language: str | None = None,
) -> str:
    """基于当前行程回答用户问答（规则 baseline，不依赖 LLM）。"""
    language = response_language or _detect_response_language(query)
    is_english = language == "en"
    days = itinerary.get("days", [])
    profile = itinerary.get("trip_profile", {})
    budget = itinerary.get("budget_summary", {})
    dest = profile.get("destination_city", "未知")

    import re as _re

    if "几天" in query or "天数" in query or _re.search(r"\bhow\s+many\s+days\b", query, _re.I):
        if is_english:
            return f"The current itinerary is {len(days)} days in {dest}."
        return f"当前行程共 {len(days)} 天，目的地为 {dest}。"
    if (
        "预算" in query
        or "花费" in query
        or "多少钱" in query
        or _re.search(r"\b(budget|cost|price|spend|expense|money)\b", query, _re.I)
    ):
        total = budget.get("total_estimate", 0)
        by_cat = budget.get("by_category", {})
        if is_english:
            parts = [f"Total budget is about {int(total)} CNY"]
            for k, v in by_cat.items():
                if v:
                    parts.append(f"{k}: {int(v)} CNY")
            return ". ".join(parts) + "."
        parts = [f"总预算约 {int(total)} 元"]
        for k, v in by_cat.items():
            if v:
                parts.append(f"{k}: {int(v)} 元")
        return "。".join(parts) + "。"
    day_match = None
    if "第" in query and "天" in query:
        cn_day_map = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        }
        m = _re.search(r"第\s*(\d+|[一二两三四五六七八九十])\s*天", query)
        if m:
            raw_idx = m.group(1)
            day_match = int(raw_idx) if raw_idx.isdigit() else cn_day_map.get(raw_idx, 0)
    if day_match is None:
        m = _re.search(r"\bday\s*(\d+)\b", query, _re.I)
        if m:
            day_match = int(m.group(1))
    if day_match:
        idx = day_match
        for d in days:
            if d.get("day_index") == idx:
                slots_desc = []
                for s in d.get("slots", []):
                    slot = s.get("slot", "")
                    activity = s.get("activity", "")
                    place = s.get("place", "未定")
                    if is_english:
                        slots_desc.append(f"{slot}: {activity} ({place})")
                    else:
                        slots_desc.append(f"{slot}：{activity}（{place}）")
                theme = d.get("theme", "")
                if is_english:
                    theme_part = f" - {theme}" if theme else ""
                    return f"Day {idx}{theme_part}: {'; '.join(slots_desc)}."
                return f"第{idx}天{' - ' + theme if theme else ''}：{'；'.join(slots_desc)}。"
        if is_english:
            return f"There is no day {idx} in the current itinerary."
        return f"行程中没有第{idx}天的安排。"

    slot_count = sum(len(d.get("slots", [])) for d in days)
    if is_english:
        total = int(budget.get("total_estimate", 0))
        return (
            f"Current itinerary: {dest}, {len(days)} days, {slot_count} scheduled time slots, "
            f"total budget {total} CNY. Ask about a specific day, for example: 'What is the plan for day N?'"
        )
    return f"当前行程：{dest} {len(days)} 天，共 {slot_count} 个时段安排，总预算 {int(budget.get('total_estimate', 0))} 元。如需了解具体某天，可以问'第N天安排是什么'。"


def _classify_local_qa_fast_path(query: str) -> dict | None:
    """Cheap deterministic QA classifier used before Structured QP LLM."""
    qp_output = query_processor.process(query)
    return qp_output if qp_output.get("intent") == "qa" else None


async def _build_local_qa_fast_response(
    *,
    request_id: str,
    conversation_id: str,
    query_text: str,
    user_id: int,
) -> StreamingResponse | None:
    started = time.perf_counter()
    state = await ConversationService.get_travel_conversation_state(conversation_id)
    itinerary = state.get("current_itinerary") if state else None
    if not itinerary:
        return None

    qp_output = _classify_local_qa_fast_path(query_text)
    if not qp_output:
        return None

    response_language = _detect_response_language(query_text)
    text = _answer_itinerary_qa(query_text, itinerary, response_language=response_language)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "qa_local_fast_path",
        extra={
            "event_type": "qa_local_fast_path",
            "conversation_id": conversation_id,
            "intent": "qa",
            "intent_detail": qp_output.get("intent_detail"),
            "qa_source": "local_itinerary",
            "qa_elapsed_ms": elapsed_ms,
            "response_language": response_language,
        },
    )
    await ConversationService.upsert_travel_conversation_state(
        conversation_id=conversation_id,
        user_id=user_id,
        last_user_query=query_text,
    )
    return StreamingResponse(
        _stream_intent_text_response(
            request_id=request_id,
            conversation_id=conversation_id,
            intent="qa",
            intent_detail=qp_output.get("intent_detail") or "qa_local",
            text=text,
            payload_extra={
                "qa_source": "local_itinerary",
                "qa_elapsed_ms": elapsed_ms,
                "response_language": response_language,
            },
        ),
        media_type="text/event-stream",
    )


async def _stream_edit_result(
    *,
    utterance: str,
    current_itinerary: dict,
    request_id: str,
    conversation_id: str,
    intent: str,
    intent_detail: str,
    user_id: int | None = None,
):
    """解析编辑 → apply patch → 流式输出编辑后行程 + diff 事件。"""
    async for line in _stream_intent_routed_event(
        request_id=request_id,
        conversation_id=conversation_id,
        intent=intent,
        intent_detail=intent_detail,
    ):
        yield line

    try:
        if not has_mutation_intent(utterance):
            yield build_event_line(
                "final_text",
                build_event_envelope(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=None,
                    payload={
                        "text": (
                            "我还不能确认你是要修改行程。"
                            "如果只是询问，我会按当前行程回答；如果要修改，请明确说“把第N天改成...”或“删掉/增加...”。"
                        )
                    },
                ),
            )
            return

        ops = parse_edit_ops(utterance, current_itinerary)
        result = apply_patch(current_itinerary, ops)

        if not result.success:
            yield build_event_line(
                "final_text",
                build_event_envelope(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=None,
                    payload={"text": result.error or "编辑失败，请重新描述修改内容。"},
                ),
            )
            return

        try:
            edited_model = ItineraryV1.model_validate(result.new_itinerary)
            changed_days = result.change_summary.get("changed_days") or []
            report = await edit_backfill_service.backfill_changed_days(edited_model, changed_days)
            if report.assumptions:
                existing = set(edited_model.validation.assumptions)
                for assumption in report.assumptions:
                    if assumption not in existing:
                        edited_model.validation.assumptions.append(assumption)
                        existing.add(assumption)
            _apply_city_center_fallback(edited_model)
            coverage = CoverageTracker().compute(edited_model)
            edited_model.validation.coverage_score = coverage.coverage_score
            result.new_itinerary = edited_model.model_dump(mode="json")
        except Exception as enrich_err:  # noqa: BLE001
            logger.warning(f"Edit backfill skipped: {enrich_err}")

        yield build_event_line(
            "edit_diff",
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=result.new_revision_id,
                payload={
                    "old_revision_id": result.old_revision_id,
                    "new_revision_id": result.new_revision_id,
                    "change_summary": result.change_summary,
                    "explanation": result.explanation,
                },
            ),
        )

        yield build_event_line(
            "final_itinerary",
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=result.new_revision_id,
                payload={
                    "itinerary": result.new_itinerary,
                    "explanation": result.explanation,
                },
            ),
        )

        try:
            await ConversationService.upsert_travel_conversation_state(
                conversation_id=conversation_id,
                user_id=user_id,
                current_revision_id=result.new_revision_id,
                trip_profile=result.new_itinerary.get("trip_profile"),
                current_itinerary=result.new_itinerary,
                last_user_query=utterance,
            )
        except Exception as persist_err:
            logger.error(f"Persist edited state failed: {persist_err}", exc_info=True)

        yield _build_sse_line(result.explanation)

    except Exception as e:
        logger.error(f"Edit flow failed: {e}", exc_info=True)
        yield build_event_line(
            "error",
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=None,
                payload={"text": f"编辑处理异常：{str(e)}"},
            ),
        )
        yield _build_sse_line(f"编辑处理异常：{str(e)}")


async def _build_reset_response(
    *,
    request_id: str,
    conversation_id: str,
    intent: str,
    intent_detail: str,
    user_id: int,
    last_user_query: str,
) -> StreamingResponse:
    """统一构造 reset 意图的 SSE 响应，供 query 与 resume 复用。"""
    clarification_service.clear_pending(conversation_id)
    await ConversationService.reset_travel_conversation_state(
        conversation_id=conversation_id,
        user_id=user_id,
        last_user_query=last_user_query,
    )
    return StreamingResponse(
        _stream_intent_text_response(
            request_id=request_id,
            conversation_id=conversation_id,
            intent=intent,
            intent_detail=intent_detail,
            text="已为当前会话重置行程状态，你可以重新输入新的出行需求。",
            event_name="reset_done",
        ),
        media_type="text/event-stream",
    )


async def _build_edit_qa_response(
    *,
    request_id: str,
    conversation_id: str,
    intent: str,
    intent_detail: str,
    query_text: str,
    user_id: int,
) -> StreamingResponse:
    """统一构造 edit/qa 意图的 SSE 响应，供 query 与 resume 复用。"""
    state = await ConversationService.get_travel_conversation_state(conversation_id)
    has_itinerary = bool(state and state.get("current_itinerary"))
    if not has_itinerary:
        return StreamingResponse(
            _stream_intent_text_response(
                request_id=request_id,
                conversation_id=conversation_id,
                intent=intent,
                intent_detail=intent_detail,
                text="当前会话还没有可编辑的行程，请先描述目的地、天数和预算生成草案。",
            ),
            media_type="text/event-stream",
        )
    if intent == "edit":
        return StreamingResponse(
            _stream_edit_result(
                utterance=query_text,
                current_itinerary=state["current_itinerary"],
                request_id=request_id,
                conversation_id=conversation_id,
                intent=intent,
                intent_detail=intent_detail,
                user_id=user_id,
            ),
            media_type="text/event-stream",
        )
    response_language = _detect_response_language(query_text)
    text = _answer_itinerary_qa(
        query_text,
        state["current_itinerary"],
        response_language=response_language,
    )
    return StreamingResponse(
        _stream_intent_text_response(
            request_id=request_id,
            conversation_id=conversation_id,
            intent=intent,
            intent_detail=intent_detail,
            text=text,
            payload_extra={"response_language": response_language},
        ),
        media_type="text/event-stream",
    )


# 创建行程恢复请求模型
class LangGraphResumeRequest(BaseModel):
    """恢复会话请求体。"""
    query: str
    user_id: int
    conversation_id: str

# 双路由别名：`/travel/*` 是新语义入口，`/langgraph/*` 兼容旧前端调用。
@router.post("/travel/query")
@router.post("/langgraph/query")
async def langgraph_query(
    query: str = Form(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
):
    """旅行规划主入口：新建/续跑会话 + 澄清门槛 + SSE 流式输出。"""
    request_fingerprint: str | None = None
    # 处理行程查询请求
    try:
        logger.info(f"Processing travel planning query for user {user_id} and conversation {conversation_id}")
        await _ensure_user_exists(user_id)

        # 图片是可选输入：用于多模态增强（如景点/酒店截图），不是行程生成必填项。
        image_path = None
        if image:
            image_dir = Path("uploads/images")
            image_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_name, ext = os.path.splitext(image.filename)
            new_filename = f"{original_name}_{timestamp}{ext}"
            image_path = image_dir / new_filename

            content = await image.read()
            with open(image_path, "wb") as f:
                f.write(content)

            logger.info(f"Saved image {new_filename} for user {user_id}")

        # 会话线程ID：有 conversation_id 就复用，否则生成新会话。
        thread_id = conversation_id if conversation_id else new_uuid()
        request_id = new_uuid()
        request_fingerprint = _request_fingerprint(
            user_id=user_id,
            conversation_id=conversation_id,
            query=query,
        )
        if not _try_acquire_request_fingerprint(request_fingerprint):
            logger.info(
                "duplicate_travel_request",
                extra={
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "dedupe_ttl_seconds": settings.TRAVEL_REQUEST_DEDUPE_TTL_SECONDS,
                },
            )
            response = _build_duplicate_request_response(
                request_id=request_id,
                conversation_id=thread_id,
            )
            response.headers["X-Conversation-ID"] = thread_id
            return response

        if conversation_id and not clarification_service.has_pending(thread_id):
            local_qa_response = await _build_local_qa_fast_response(
                request_id=request_id,
                conversation_id=thread_id,
                query_text=query,
                user_id=user_id,
            )
            if local_qa_response is not None:
                local_qa_response.headers["X-Conversation-ID"] = thread_id
                return _guard_response(local_qa_response, request_fingerprint)

        qp_output = await _process_qp(query, thread_id)
        normalized_query = qp_output["normalized_query"]
        recall_query = qp_output["recall_query"]
        logger.info(
            "QP parsed",
            extra={
                "event_type": "qp_parsed",
                "conversation_id": thread_id,
                "intent": qp_output["intent"],
                "intent_detail": qp_output["intent_detail"],
                "missing_required": qp_output["missing_required"],
                "qp_source": qp_output.get("qp_source"),
                "confidence": qp_output.get("confidence"),
                "fallback_reason": qp_output.get("fallback_reason"),
            },
        )
        intent = qp_output["intent"]
        intent_detail = qp_output["intent_detail"]

        await ConversationService.upsert_travel_conversation_state(
            conversation_id=thread_id,
            user_id=user_id,
            last_user_query=query,
        )
        # 配置会透传到 LangGraph 节点（例如 image_path 可触发图片分析分支）。
        thread_config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
                "image_path": str(image_path) if image_path else None,
            }
        }

        if intent == "reset":
            clarification_service.clear_pending(thread_id)
            response = await _build_reset_response(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
                user_id=user_id,
                last_user_query=query,
            )
            response.headers["X-Conversation-ID"] = thread_id
            return _guard_response(response, request_fingerprint)

        # --- Guided conversation: follow-up to pending clarification ---
        if clarification_service.has_pending(thread_id):
            decision = clarification_service.continue_pending(
                thread_id=thread_id, query=normalized_query,
            )
            if decision.get("need_clarification"):
                logger.info(
                    f"Guided follow-up for thread={thread_id}, "
                    f"missing_hard={decision['missing_hard']}"
                )
                known_text, missing_text = clarification_service.get_constraint_context(thread_id)
                guided_text = await _generate_guided_response(
                    query, thread_id, known_text, missing_text,
                )
                response = StreamingResponse(
                    _stream_intent_text_response(
                        request_id=request_id,
                        conversation_id=thread_id,
                        intent="create",
                        intent_detail="guided_clarification",
                        text=guided_text,
                    ),
                    media_type="text/event-stream",
                )
                response.headers["X-Conversation-ID"] = thread_id
                return _guard_response(response, request_fingerprint)

            if decision.get("has_pending"):
                combined_query = decision["combined_query"]
                combined_qp = await _process_qp(combined_query, thread_id)
                combined_recall = combined_qp["recall_query"]
                logger.info(
                    f"Guided conversation complete for thread={thread_id}, "
                    "generating itinerary from combined constraints."
                )

                async def process_guided_complete():
                    async for line in _stream_intent_routed_event(
                        request_id=request_id,
                        conversation_id=thread_id,
                        intent="create",
                        intent_detail="first_create",
                    ):
                        yield line
                    async for line in _stream_minimal_itinerary(
                        query_text=combined_recall,
                        original_query=combined_query,
                        thread_config=thread_config,
                        conversation_id=thread_id,
                        request_id=request_id,
                        user_id=user_id,
                    ):
                        yield line

                response = StreamingResponse(
                    process_guided_complete(), media_type="text/event-stream",
                )
                response.headers["X-Conversation-ID"] = thread_id
                return _guard_response(response, request_fingerprint)

        if intent in {"edit", "qa"}:
            response = await _build_edit_qa_response(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
                query_text=query,
                user_id=user_id,
            )
            response.headers["X-Conversation-ID"] = thread_id
            return _guard_response(response, request_fingerprint)

        if intent == "chat":
            chat_text = await _generate_chat_response(query, thread_id)
            response = StreamingResponse(
                _stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                    text=chat_text,
                ),
                media_type="text/event-stream",
            )
            response.headers["X-Conversation-ID"] = thread_id
            return _guard_response(response, request_fingerprint)

        # --- Create intent: first clarification gate ---
        decision = clarification_service.start_new(thread_id=thread_id, query=normalized_query)
        if decision["need_clarification"]:
            logger.info(
                f"Guided clarification for thread={thread_id}, "
                f"missing_hard={decision['missing_hard']}"
            )
            known_text, missing_text = clarification_service.get_constraint_context(thread_id)
            guided_text = await _generate_guided_response(
                query, thread_id, known_text, missing_text,
            )
            response = StreamingResponse(
                _stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent="create",
                    intent_detail="guided_clarification",
                    text=guided_text,
                ),
                media_type="text/event-stream",
            )
            response.headers["X-Conversation-ID"] = thread_id
            return _guard_response(response, request_fingerprint)

        logger.info("Clarification gate passed, generating minimal itinerary draft.")

        async def process_stream():
            async for line in _stream_intent_routed_event(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
            ):
                yield line
            async for line in _stream_minimal_itinerary(
                query_text=recall_query,
                original_query=query,
                thread_config=thread_config,
                conversation_id=thread_id,
                request_id=request_id,
                user_id=user_id,
            ):
                yield line

        response = StreamingResponse(process_stream(), media_type="text/event-stream")
        response.headers["X-Conversation-ID"] = thread_id
        return _guard_response(response, request_fingerprint)
    except HTTPException:
        _release_request_fingerprint(request_fingerprint)
        raise
    except Exception as e:
        _release_request_fingerprint(request_fingerprint)
        logger.error(f"LangGraph query error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 创建行程恢复路由
@router.post("/travel/resume")
@router.post("/langgraph/resume")
async def langgraph_resume(request: LangGraphResumeRequest):
    """恢复旅行规划流程：优先补全 pending 澄清，再 resume 图执行。"""
    request_fingerprint: str | None = None
    # 处理行程恢复请求
    try:
        logger.info(f"Resuming travel planning query for user {request.user_id} with conversation {request.conversation_id}")
        await _ensure_user_exists(request.user_id)

        # 创建线程ID
        thread_id = request.conversation_id
        request_id = new_uuid()
        request_fingerprint = _request_fingerprint(
            user_id=request.user_id,
            conversation_id=thread_id,
            query=request.query,
        )
        if not _try_acquire_request_fingerprint(request_fingerprint):
            logger.info(
                "duplicate_travel_resume_request",
                extra={
                    "conversation_id": thread_id,
                    "user_id": request.user_id,
                    "dedupe_ttl_seconds": settings.TRAVEL_REQUEST_DEDUPE_TTL_SECONDS,
                },
            )
            response = _build_duplicate_request_response(
                request_id=request_id,
                conversation_id=thread_id,
            )
            response.headers["X-Conversation-ID"] = thread_id
            return response

        if not clarification_service.has_pending(thread_id):
            local_qa_response = await _build_local_qa_fast_response(
                request_id=request_id,
                conversation_id=thread_id,
                query_text=request.query,
                user_id=request.user_id,
            )
            if local_qa_response is not None:
                local_qa_response.headers["X-Conversation-ID"] = thread_id
                return _guard_response(local_qa_response, request_fingerprint)

        qp_output = await _process_qp(request.query, thread_id)
        normalized_query = qp_output["normalized_query"]
        recall_query = qp_output["recall_query"]
        logger.info(
            "QP parsed",
            extra={
                "event_type": "qp_parsed",
                "conversation_id": thread_id,
                "intent": qp_output["intent"],
                "intent_detail": qp_output["intent_detail"],
                "missing_required": qp_output["missing_required"],
                "qp_source": qp_output.get("qp_source"),
                "confidence": qp_output.get("confidence"),
                "fallback_reason": qp_output.get("fallback_reason"),
            },
        )
        intent = qp_output["intent"]
        intent_detail = qp_output["intent_detail"]

        await ConversationService.upsert_travel_conversation_state(
            conversation_id=thread_id,
            user_id=request.user_id,
            last_user_query=request.query,
        )
        thread_config = {"configurable": {"thread_id": thread_id, "user_id": request.user_id}}

        if intent == "reset":
            response = await _build_reset_response(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
                user_id=request.user_id,
                last_user_query=request.query,
            )
            response.headers["X-Conversation-ID"] = thread_id
            return _guard_response(response, request_fingerprint)

        # 若该线程仍有待澄清项，优先完成澄清闭环。
        if clarification_service.has_pending(thread_id):
            decision = clarification_service.continue_pending(thread_id=thread_id, query=normalized_query)
            if decision.get("need_clarification"):
                # 创建澄清响应
                logger.info(
                    f"Clarification still required for thread={thread_id}, "
                    f"missing_hard={decision['missing_hard']}, missing_soft={decision['missing_soft']}"
                )
                # 创建流响应
                async def process_clarification():
                    async for line in _stream_intent_routed_event(
                        request_id=request_id,
                        conversation_id=thread_id,
                        intent=intent,
                        intent_detail=intent_detail,
                    ):
                        yield line
                    async for line in _stream_clarification_events(
                        request_id=request_id,
                        conversation_id=thread_id,
                        missing_hard=decision["missing_hard"],
                        missing_soft=decision["missing_soft"],
                    ):
                        yield line
                response = StreamingResponse(
                    process_clarification(),
                    media_type="text/event-stream",
                )
                response.headers["X-Conversation-ID"] = thread_id
                return _guard_response(response, request_fingerprint)

            # 将初始 query 与补充信息合并后重启输入，避免上下文丢失。
            combined_query = decision["combined_query"]
            combined_qp_output = await _process_qp(combined_query, thread_id)
            combined_recall_query = combined_qp_output["recall_query"]
            logger.info(f"Clarification completed for thread={thread_id}, continuing planning flow.")

            # 创建流响应
            async def process_resume_after_clarification():
                async for line in _stream_intent_routed_event(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                ):
                    yield line
                async for line in _stream_minimal_itinerary(
                    query_text=combined_recall_query,
                    original_query=combined_query,
                    thread_config=thread_config,
                    conversation_id=thread_id,
                    request_id=request_id,
                    user_id=request.user_id,
                ):
                    yield line

            response = StreamingResponse(process_resume_after_clarification(), media_type="text/event-stream")
            response.headers["X-Conversation-ID"] = thread_id
            return _guard_response(response, request_fingerprint)

        if intent in {"edit", "qa"}:
            response = await _build_edit_qa_response(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
                query_text=request.query,
                user_id=request.user_id,
            )
            response.headers["X-Conversation-ID"] = thread_id
            return _guard_response(response, request_fingerprint)

        # 无 pending 时，直接按当前补充信息生成最小结构化草案。
        async def process_resume():
            async for line in _stream_intent_routed_event(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
            ):
                yield line
            async for line in _stream_minimal_itinerary(
                query_text=recall_query,
                original_query=request.query,
                thread_config=thread_config,
                conversation_id=thread_id,
                request_id=request_id,
                user_id=request.user_id,
            ):
                yield line

        response = StreamingResponse(process_resume(), media_type="text/event-stream")
        response.headers["X-Conversation-ID"] = thread_id
        return _guard_response(response, request_fingerprint)

    except HTTPException:
        _release_request_fingerprint(request_fingerprint)
        raise
    except Exception as e:
        _release_request_fingerprint(request_fingerprint)
        logger.error(f"LangGraph resume error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/travel/state/{conversation_id}")
async def get_travel_state(conversation_id: str):
    """读取会话当前行程状态（T-M2-010 验收辅助接口）。"""
    try:
        state = await ConversationService.get_travel_conversation_state(conversation_id)
        if not state:
            return {"conversation_id": conversation_id, "state": None}
        return {"conversation_id": conversation_id, "state": state}
    except Exception as e:
        logger.error(f"Get travel state error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 创建图片上传路由
@router.post("/upload/image")
async def upload_image(
    image: UploadFile = File(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None),
):
    """独立图片上传接口：只做文件落盘并返回元数据。"""
    # 处理图片上传请求
    try:
        # 按会话隔离目录，便于后续会话级清理与追踪。
        image_dir = Path("uploads/images")
        # 如果存在会话ID，则使用会话ID作为图片目录
        if conversation_id:
            image_dir = image_dir / conversation_id
        image_dir.mkdir(parents=True, exist_ok=True)

        # 创建时间戳
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 创建图片文件名
        original_name, ext = os.path.splitext(image.filename)
        new_filename = f"{original_name}_{timestamp}{ext}"
        # 创建图片路径
        image_path = image_dir / new_filename
        # 读取图片内容

        content = await image.read()
        # 写入图片内容
        with open(image_path, "wb") as f:
            f.write(content)

        # 创建图片信息
        image_info = {
            "filename": new_filename,
            "original_name": image.filename,
            "size": len(content),
            "type": image.content_type,
            "path": str(image_path).replace("\\", "/"),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "upload_time": timestamp,
        }

        # 记录图片上传日志
        logger.info(f"Image uploaded: {image_info}")
        # 返回图片信息
        return image_info
    except Exception as e:
        # 记录图片上传失败日志
        logger.error(f"Image upload failed for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
