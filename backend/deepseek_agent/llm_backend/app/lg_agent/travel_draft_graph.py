import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

# 行程草案生成图
from app.schemas.itinerary_v1 import (
    BudgetSummary,
    ItineraryDay,
    ItineraryV1,
    TripConstraints,
    TripProfile,
)
# 行程草案规则
from app.domain.travel.draft_rules import DRAFT_CONFIG, DraftConfig
# 行程草案构建器
from app.domain.travel.draft_builder import (
    build_slots,
    extract_budget,
    extract_days,
    extract_destination,
    extract_traveler_type,
)


# 行程草案输入
class TravelDraftInput(TypedDict):
    query: str


# 行程草案状态
class TravelDraftState(TravelDraftInput):
    final_itinerary: dict | None
    explanation: str | None
    final_text: str | None


# 生成行程草案
async def generate_travel_draft(state: TravelDraftState) -> dict:
    query = state.get("query", "").strip()
    days_count = extract_days(query)
    total_budget = extract_budget(query)
    destination = extract_destination(query)
    traveler_type = extract_traveler_type(query)

    # 缺失P0
    missing_p0 = []
    # 目的地缺失
    if not destination:
        missing_p0.append(DRAFT_CONFIG.required_labels[0])
    # 天数缺失
    if not days_count:
        missing_p0.append(DRAFT_CONFIG.required_labels[1])
    # 预算缺失
    if total_budget is None:
        missing_p0.append(DRAFT_CONFIG.required_labels[2])

    # 缺失P0
    if missing_p0:
        return {
            "final_itinerary": None,
            "explanation": None,
            "final_text": DRAFT_CONFIG.missing_p0_template.format(
                missing_fields="、".join(missing_p0)
            ),
        }

    # 假设
    assumptions = []
    # 出行人群缺失
    if not traveler_type:
        assumptions.append(DRAFT_CONFIG.traveler_default_assumption)

    # 行程草案
    itinerary = ItineraryV1(
        itinerary_id=str(uuid.uuid4()),
        revision_id=str(uuid.uuid4()),
        # 行程概况
        trip_profile=TripProfile(
            destination_city=destination,
            constraints=TripConstraints(
                # 预算范围
                budget_range=DRAFT_CONFIG.budget_hint_template.format(budget=int(total_budget)),
                # 出行人群类型
                traveler_type=traveler_type,
            ),
        ),
        # 行程天数
        days=[ItineraryDay(day_index=i, slots=build_slots(i)) for i in range(1, days_count + 1)],
        # 预算概况
        budget_summary=BudgetSummary(total_estimate=total_budget),
    )
    # 假设
    itinerary.validation.assumptions.extend(assumptions)

    # 解释模板
    explanation = DRAFT_CONFIG.explanation_template.format(days=days_count)
    if assumptions:
        explanation = f"{explanation} {' '.join(assumptions)}".strip()

    # 返回行程草案
    return {
        "final_itinerary": itinerary.model_dump(mode="json"),
        "explanation": explanation,
        "final_text": None,
    }


# 构建行程草案生成图
builder = StateGraph(TravelDraftState, input=TravelDraftInput)
builder.add_node("generate_travel_draft", generate_travel_draft)
builder.add_edge(START, "generate_travel_draft")
builder.add_edge("generate_travel_draft", END)

# 编译行程草案生成图
travel_draft_graph = builder.compile()
