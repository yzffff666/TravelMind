import json
import uuid
from typing import TypedDict

from langchain_deepseek import ChatDeepSeek
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph

from app.core.config import ServiceType, settings
from app.core.logger import get_logger
from app.domain.travel.draft_builder import (
    build_slots,
    extract_budget,
    extract_days,
    extract_destination,
    extract_traveler_type,
)
from app.domain.travel.draft_prompts import (
    TRAVEL_DRAFT_SYSTEM_PROMPT,
    TRAVEL_DRAFT_USER_PROMPT_TEMPLATE,
)
from app.domain.travel.draft_rules import DRAFT_CONFIG
from app.schemas.itinerary_v1 import (
    BudgetByCategory,
    BudgetSummary,
    CostBreakdown,
    ItineraryDay,
    ItinerarySlot,
    ItineraryV1,
    TripConstraints,
    TripProfile,
    ValidationResult,
)

logger = get_logger(service="travel_draft_graph")


class TravelDraftInput(TypedDict):
    query: str

# TravelDraftState 状态定义
class TravelDraftState(TravelDraftInput):
    final_itinerary: dict | None
    explanation: str | None
    final_text: str | None

# 根据 .env 配置选择 LLM 实例。
def _get_llm():
    """根据 .env 配置选择 LLM 实例。"""
    if settings.AGENT_SERVICE == ServiceType.DEEPSEEK:
        return ChatDeepSeek(
            api_key=settings.DEEPSEEK_API_KEY,
            model_name=settings.DEEPSEEK_MODEL,
            temperature=0.7,
            tags=["travel_draft"],
        )
    return ChatOllama(
        model=settings.OLLAMA_AGENT_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.7,
        tags=["travel_draft"],
    )

# M1 模板降级：LLM 不可用时输出占位行程。
def _build_template_itinerary(
    destination: str,
    days_count: int,
    total_budget: float,
    traveler_type: str | None,
    assumptions: list[str],
) -> ItineraryV1:
    """M1 模板降级：LLM 不可用时输出占位行程。"""
    itinerary = ItineraryV1(
        itinerary_id=str(uuid.uuid4()),
        revision_id=str(uuid.uuid4()),
        trip_profile=TripProfile(
            destination_city=destination,
            constraints=TripConstraints(
                budget_range=DRAFT_CONFIG.budget_hint_template.format(budget=int(total_budget)),
                traveler_type=traveler_type,
            ),
        ),
        days=[
            ItineraryDay(day_index=i, slots=build_slots(i))
            for i in range(1, days_count + 1)
        ],
        budget_summary=BudgetSummary(total_estimate=total_budget),
    )
    itinerary.validation.assumptions.extend(assumptions)
    return itinerary

# LLM 输出解析：将 LLM 返回的 JSON 解析为 ItineraryV1。
def _parse_llm_itinerary(
    raw: str,
    destination: str,
    days_count: int,
    total_budget: float,
    traveler_type: str | None,
    preferences: list[str],
    assumptions: list[str],
) -> ItineraryV1:
    """将 LLM 返回的 JSON 解析为 ItineraryV1。"""
    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3].strip()

    data = json.loads(text)

    days = []
    # 遍历 data 中的 days，构建 ItineraryDay 列表。
    for day_data in data.get("days", []):
        slots = []
        # 遍历 day_data 中的 slots，构建 ItinerarySlot 列表。
        for slot_data in day_data.get("slots", []):
            cb = slot_data.get("cost_breakdown")
            cost_breakdown = None
            if cb and isinstance(cb, dict):
                cost_breakdown = CostBreakdown(
                    transport=cb.get("transport"),
                    hotel=cb.get("hotel"),
                    tickets=cb.get("tickets"),
                    food=cb.get("food"),
                    other=cb.get("other"),
                )
            # 构建 ItinerarySlot 实例并添加到 slots 列表。
            slots.append(ItinerarySlot(
                slot=slot_data.get("slot", "上午"),
                activity=slot_data.get("activity", ""),
                place=slot_data.get("place"),
                transit=slot_data.get("transit"),
                cost_breakdown=cost_breakdown,
            ))
        # 构建 ItineraryDay 实例并添加到 days 列表。
        days.append(ItineraryDay(
            day_index=day_data.get("day_index", len(days) + 1),
            theme=day_data.get("theme"),
            slots=slots if slots else build_slots(len(days) + 1),
        ))

    # 如果 LLM 未返回有效天数数据，则降级为模板。
    if not days:
        days = [
            ItineraryDay(day_index=i, slots=build_slots(i))
            for i in range(1, days_count + 1)
        ]
        assumptions.append("LLM 未返回有效天数数据，已降级为模板。")

    # 构建 BudgetSummary 实例。
    bs = data.get("budget_summary", {})
    by_cat = bs.get("by_category", {})
    # 构建 BudgetSummary 实例。
    budget_summary = BudgetSummary(
        total_estimate=bs.get("total_estimate", total_budget),
        uncertainty_note=bs.get("uncertainty_note"),
        by_category=BudgetByCategory(
            transport=by_cat.get("transport"),
            hotel=by_cat.get("hotel"),
            tickets=by_cat.get("tickets"),
            food=by_cat.get("food"),
            other=by_cat.get("other"),
        ),
    )

    # 构建 ItineraryV1 实例。
    itinerary = ItineraryV1(
        itinerary_id=str(uuid.uuid4()),
        revision_id=str(uuid.uuid4()),
        trip_profile=TripProfile(
            destination_city=destination,
            constraints=TripConstraints(
                budget_range=DRAFT_CONFIG.budget_hint_template.format(budget=int(total_budget)),
                traveler_type=traveler_type,
                preferences=preferences,
            ),
        ),
        days=days,
        budget_summary=budget_summary,
    )
    itinerary.validation.assumptions.extend(assumptions)
    return itinerary

# 主图节点：根据用户查询生成行程草案。
async def generate_travel_draft(state: TravelDraftState) -> dict:
    # 从状态中获取用户查询。
    query = state.get("query", "").strip()
    # 从用户查询中提取天数。
    days_count = extract_days(query)
    # 从用户查询中提取预算。
    total_budget = extract_budget(query)
    # 从用户查询中提取目的地。
    destination = extract_destination(query)
    # 从用户查询中提取旅行者类型。
    traveler_type = extract_traveler_type(query)

    missing_p0 = []
    # 如果目的地为空，则添加到 missing_p0 列表。
    if not destination:
        missing_p0.append(DRAFT_CONFIG.required_labels[0])
    # 如果天数为空，则添加到 missing_p0 列表。
    if not days_count:
        missing_p0.append(DRAFT_CONFIG.required_labels[1])
    # 如果预算为空，则添加到 missing_p0 列表。
    if total_budget is None:
        missing_p0.append(DRAFT_CONFIG.required_labels[2])

    # 如果 missing_p0 列表不为空，则返回 missing_p0 列表。
    if missing_p0:
        return {
            "final_itinerary": None,
            "explanation": None,
            "final_text": DRAFT_CONFIG.missing_p0_template.format(
                missing_fields="、".join(missing_p0)
            ),
        }

    assumptions: list[str] = []
    # 如果旅行者类型为空，则添加到 assumptions 列表。
    if not traveler_type:
        assumptions.append(DRAFT_CONFIG.traveler_default_assumption)

    # 从 QP_RULES 中提取偏好。
    from app.domain.travel.qp_rules import QP_RULES
    preferences = [kw for kw in QP_RULES.preference_keywords if kw in query]
    pace = None
    # 从 QP_RULES 中提取节奏。
    for key, value in QP_RULES.pace_keywords.items():
        if key in query:
            pace = value
            break

    # --- 尝试 LLM 生成 ---
    try:
        llm = _get_llm()
        # 构建用户 prompt。
        user_prompt = TRAVEL_DRAFT_USER_PROMPT_TEMPLATE.format(
            destination_city=destination,
            days=days_count,
            budget=int(total_budget),
            traveler_type=traveler_type or "通用休闲",
            preferences="、".join(preferences) if preferences else "无特别偏好",
            pace=pace or "适中",
        )
        # 构建消息列表。
        messages = [
            {"role": "system", "content": TRAVEL_DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        logger.info(f"Calling LLM for travel draft: {destination} {days_count}天 预算{int(total_budget)}")
        # 调用 LLM。
        response = await llm.ainvoke(messages)
        # 获取 LLM 返回的原始内容。
        raw_content = response.content

        # 解析 LLM 返回的原始内容。
        itinerary = _parse_llm_itinerary(
            raw=raw_content,
            destination=destination,
            days_count=days_count,
            total_budget=total_budget,
            traveler_type=traveler_type,
            preferences=preferences,
            assumptions=assumptions,
        )
        # 构建解释。
        explanation = (
            f"已为你生成 {destination} {days_count} 天行程草案"
            f"（预算 {int(total_budget)} 元"
            f"{'，' + traveler_type if traveler_type else ''}"
            f"{'，偏好 ' + '、'.join(preferences) if preferences else ''}"
            f"）。"
        )
        logger.info("LLM travel draft generated successfully")

    except Exception as e:
        logger.warning(f"LLM draft generation failed, falling back to template: {e}")
        assumptions.append(f"LLM 生成失败（{type(e).__name__}），已降级为模板草案。")
        # 构建模板行程。
        itinerary = _build_template_itinerary(
            destination=destination,
            days_count=days_count,
            total_budget=total_budget,
            traveler_type=traveler_type,
            assumptions=assumptions,
        )
        # 构建解释。
        explanation = DRAFT_CONFIG.explanation_template.format(days=days_count)
        if assumptions:
            explanation = f"{explanation} {' '.join(assumptions)}".strip()

    # 返回结果。
    return {
        "final_itinerary": itinerary.model_dump(mode="json"),
        "explanation": explanation,
        "final_text": None,
    }


builder = StateGraph(TravelDraftState, input=TravelDraftInput)
builder.add_node("generate_travel_draft", generate_travel_draft)
builder.add_edge(START, "generate_travel_draft")
builder.add_edge("generate_travel_draft", END)

travel_draft_graph = builder.compile()
