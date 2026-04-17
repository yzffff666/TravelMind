import json
import re as _re
import time
import uuid
from typing import Any, TypedDict

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
    TRAVEL_DRAFT_CANDIDATES_SECTION,
    TRAVEL_DRAFT_SYSTEM_PROMPT,
    TRAVEL_DRAFT_USER_PROMPT_TEMPLATE,
)
from app.domain.travel.draft_rules import DRAFT_CONFIG
from app.domain.travel.qp_rules import QP_RULES
from app.domain.travel.query_processor import TravelQueryProcessor
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
from app.services.constraint_filter import ConstraintFilter
from app.services.coverage_tracker import CoverageTracker
from app.services.evidence_builder import EvidenceBuilder, PipelineResult
from app.services.ranking_scorer import RankingScorer
from app.services.recall_service import RecallService

logger = get_logger(service="travel_draft_graph")


# ---------------------------------------------------------------------------
# Pipeline services — lazy singleton to avoid re-creating on every request.
# ---------------------------------------------------------------------------
_pipeline_qp: TravelQueryProcessor | None = None
_pipeline_recall: RecallService | None = None
_pipeline_scorer: RankingScorer | None = None
_pipeline_filter: ConstraintFilter | None = None
_pipeline_eb: EvidenceBuilder | None = None


def _get_pipeline():
    """Return (qp, recall, scorer, filter, evidence_builder) singletons."""
    global _pipeline_qp, _pipeline_recall, _pipeline_scorer, _pipeline_filter, _pipeline_eb
    if _pipeline_qp is None:
        _pipeline_qp = TravelQueryProcessor()
        _pipeline_recall = RecallService(include_mock_fallback=True)
        _pipeline_scorer = RankingScorer()
        _pipeline_filter = ConstraintFilter()
        _pipeline_eb = EvidenceBuilder()
    return _pipeline_qp, _pipeline_recall, _pipeline_scorer, _pipeline_filter, _pipeline_eb


_MAX_CANDIDATES_IN_PROMPT = 10


def _format_candidates_for_prompt(pipeline_result: PipelineResult | None) -> str:
    """Format pipeline candidates into a text section for the LLM prompt.

    Returns an empty string if there are no candidates (LLM falls back
    to its own knowledge).  Caps at ``_MAX_CANDIDATES_IN_PROMPT`` to
    stay within LLM token budgets.
    """
    if not pipeline_result or not pipeline_result.candidates:
        return ""

    capped = pipeline_result.candidates[:_MAX_CANDIDATES_IN_PROMPT]
    lines: list[str] = []
    for i, sc in enumerate(capped, 1):
        c = sc.candidate
        tags_str = "、".join(c.tags[:3]) if c.tags else "综合"
        rating = c.extra.get("rating")
        rating_str = f"评分{rating}" if rating else "暂无评分"
        cost = c.extra.get("cost_estimate")
        cost_str = f"¥{cost:.0f}" if cost else "免费/未知"
        addr = c.extra.get("address", "")
        addr_str = f" | {addr}" if addr else ""
        lines.append(f"{i}. {c.title} [{tags_str}] {rating_str} 参考费用{cost_str}{addr_str}")

    return TRAVEL_DRAFT_CANDIDATES_SECTION.format(
        count=len(lines),
        candidate_lines="\n".join(lines),
    )


def _safe_coord(val: Any) -> float | None:
    """安全转换坐标值为 float，转换失败返回 None。"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _build_candidate_geo_index(
    pipeline_result: PipelineResult,
) -> dict[str, dict]:
    """Build a name→{lat, lng, image_url} lookup from pipeline candidates."""
    index: dict[str, dict] = {}
    for sc in pipeline_result.candidates:
        c = sc.candidate
        title = (c.title or "").strip()
        if not title:
            continue
        lat = c.extra.get("lat")
        lng = c.extra.get("lng")
        photos = c.extra.get("photos") or []
        image_url = c.extra.get("thumbnail") or (photos[0] if photos else None)
        entry: dict = {}
        lat_f, lng_f = _safe_coord(lat), _safe_coord(lng)
        if lat_f is not None and lng_f is not None:
            entry["lat"] = lat_f
            entry["lng"] = lng_f
        if image_url:
            entry["image_url"] = str(image_url)
        if entry:
            index[title.lower()] = entry
    return index


def _fuzzy_geo_lookup(geo_index: dict[str, dict], poi_name: str) -> dict | None:
    """Try exact match first, then substring match against geo index keys."""
    key = (poi_name or "").strip().lower()
    if not key:
        return None
    exact = geo_index.get(key)
    if exact:
        return exact
    for candidate_key, entry in geo_index.items():
        if candidate_key in key or key in candidate_key:
            return entry
    return None


# 主要城市中心坐标兜底（当 provider 无法提供具体地点坐标时使用）
_CITY_CENTERS: dict[str, tuple[float, float]] = {
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644), "深圳": (22.5431, 114.0579),
    "成都": (30.5728, 104.0668), "杭州": (30.2741, 120.1551),
    "西安": (34.3416, 108.9398), "重庆": (29.5630, 106.5516),
    "南京": (32.0603, 118.7969), "武汉": (30.5928, 114.3055),
    "苏州": (31.2989, 120.5853), "厦门": (24.4798, 118.0894),
    "青岛": (36.0671, 120.3826), "大理": (25.6065, 100.2679),
    "丽江": (26.8721, 100.2300), "三亚": (18.2528, 109.5119),
    "桂林": (25.2736, 110.2907), "黄山": (29.7147, 118.3378),
    "张家界": (29.1170, 110.4799), "九寨沟": (33.2600, 103.9170),
}


def _city_center_fallback(destination: str) -> tuple[float, float] | None:
    """返回城市中心坐标，用于地图无实际坐标时的兜底显示。"""
    for city, coords in _CITY_CENTERS.items():
        if city in destination:
            return coords
    return None


def _postprocess_with_pipeline(
    itinerary: ItineraryV1,
    pipeline_result: PipelineResult | None,
    evidence_builder: EvidenceBuilder | None,
    recall_geo_index: dict | None = None,
) -> None:
    """Attach pipeline evidence to itinerary, link refs per slot, compute coverage.

    Mutates ``itinerary`` in place.  No-op when ``pipeline_result`` is None
    (graceful degradation — the itinerary remains valid but without evidence).
    """
    if not pipeline_result or not evidence_builder:
        return

    itinerary.evidence = list(pipeline_result.evidence)

    geo_index = _build_candidate_geo_index(pipeline_result)
    if recall_geo_index:
        for k, v in recall_geo_index.items():
            if k not in geo_index:
                geo_index[k] = v

    for day in itinerary.days:
        for slot in day.slots:
            poi_name = slot.place or slot.activity
            refs = evidence_builder.link_slot(pipeline_result.evidence, poi_name)
            slot.evidence_refs = refs

            geo = _fuzzy_geo_lookup(geo_index, poi_name)
            if geo:
                if "lat" in geo and "lng" in geo and slot.location is None:
                    from app.schemas.itinerary_v1 import Location
                    slot.location = Location(lat=geo["lat"], lng=geo["lng"])
                if "image_url" in geo and slot.image_url is None:
                    slot.image_url = geo["image_url"]

    existing = set(itinerary.validation.assumptions)
    for a in pipeline_result.assumptions:
        if a not in existing:
            itinerary.validation.assumptions.append(a)
            existing.add(a)

    # 城市中心坐标兜底：slot 经过 geo 匹配仍无坐标时，用城市中心占位，前端地图不会空白
    destination = itinerary.trip_profile.destination_city or ""
    fallback = _city_center_fallback(destination)
    if fallback:
        from app.schemas.itinerary_v1 import Location
        for day in itinerary.days:
            for slot in day.slots:
                if slot.location is None:
                    slot.location = Location(lat=fallback[0], lng=fallback[1])

    tracker = CoverageTracker()
    report = tracker.compute(itinerary)
    itinerary.validation.coverage_score = report.coverage_score

    logger.info(
        f"Post-processing: evidence_count={len(itinerary.evidence)}, "
        f"coverage={report.coverage_score:.2f}, "
        f"meets_target={report.meets_target}"
    )


# ---------------------------------------------------------------------------
# State definitions — multi-node architecture
# ---------------------------------------------------------------------------

class TravelDraftInput(TypedDict):
    query: str


class TravelDraftState(TravelDraftInput):
    # -- extract_node outputs --
    destination: str | None
    days_count: int | None
    total_budget: float | None
    traveler_type: str | None
    preferences: list[str]
    pace: str | None
    assumptions: list[str]
    missing_p0: list[str]

    # -- recall_node outputs --
    pipeline_result: Any  # PipelineResult or None (not serialisable as TypedDict)
    recall_degraded: bool
    recall_geo_index: dict  # full name→{lat,lng,image_url} from ALL recalled candidates

    # -- llm_draft_node outputs --
    raw_llm_content: str | None
    itinerary: dict | None

    # -- final outputs (postprocess_node / early_exit) --
    final_itinerary: dict | None
    explanation: str | None
    final_text: str | None

    # -- per-node timing --
    perf: dict


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _get_llm():
    """Select LLM instance based on .env configuration."""
    if settings.AGENT_SERVICE == ServiceType.DEEPSEEK:
        return ChatDeepSeek(
            api_key=settings.DEEPSEEK_API_KEY,
            model_name=settings.DEEPSEEK_MODEL,
            temperature=0.7,
            max_tokens=4096,
            tags=["travel_draft"],
        )
    return ChatOllama(
        model=settings.OLLAMA_AGENT_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.7,
        tags=["travel_draft"],
    )


def _build_template_itinerary(
    destination: str,
    days_count: int,
    total_budget: float,
    traveler_type: str | None,
    assumptions: list[str],
) -> ItineraryV1:
    """Template fallback when LLM is unavailable."""
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


def _repair_json(text: str) -> str:
    """Best-effort repair of common LLM JSON mistakes before parsing."""
    t = text.strip().lstrip("\ufeff")

    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl >= 0:
            t = t[first_nl + 1:]
        if t.endswith("```"):
            t = t[:-3].strip()

    if not t.startswith("{"):
        match = _re.search(r"\{", t)
        if match:
            t = t[match.start():]

    last_brace = t.rfind("}")
    if last_brace >= 0 and last_brace < len(t) - 1:
        t = t[: last_brace + 1]

    t = _re.sub(r"//[^\n]*", "", t)
    t = _re.sub(r",\s*([}\]])", r"\1", t)

    return t


def _parse_llm_itinerary(
    raw: str,
    destination: str,
    days_count: int,
    total_budget: float,
    traveler_type: str | None,
    preferences: list[str],
    assumptions: list[str],
) -> ItineraryV1:
    """Parse LLM JSON response into ItineraryV1 with error repair."""
    text = _repair_json(raw)
    data = json.loads(text)

    days = []
    for day_data in data.get("days", []):
        slots = []
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
            slots.append(ItinerarySlot(
                slot=slot_data.get("slot", "上午"),
                activity=slot_data.get("activity", ""),
                place=slot_data.get("place"),
                transit=slot_data.get("transit"),
                cost_breakdown=cost_breakdown,
            ))
        days.append(ItineraryDay(
            day_index=day_data.get("day_index", len(days) + 1),
            theme=day_data.get("theme"),
            slots=slots if slots else build_slots(len(days) + 1),
        ))

    if not days:
        days = [
            ItineraryDay(day_index=i, slots=build_slots(i))
            for i in range(1, days_count + 1)
        ]
        assumptions.append("LLM 未返回有效天数数据，已降级为模板。")

    bs = data.get("budget_summary", {})
    by_cat = bs.get("by_category", {})
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


# ===================================================================
# Graph Nodes
# ===================================================================

async def extract_node(state: TravelDraftState) -> dict:
    """Node 1: Extract travel constraints from query and validate P0 fields."""
    t0 = time.perf_counter()
    query = state.get("query", "").strip()

    destination = extract_destination(query)
    days_count = extract_days(query)
    total_budget = extract_budget(query)
    traveler_type = extract_traveler_type(query)

    missing_p0: list[str] = []
    if not destination:
        missing_p0.append(DRAFT_CONFIG.required_labels[0])
    if not days_count:
        missing_p0.append(DRAFT_CONFIG.required_labels[1])
    if total_budget is None:
        missing_p0.append(DRAFT_CONFIG.required_labels[2])

    assumptions: list[str] = []
    if not traveler_type:
        assumptions.append(DRAFT_CONFIG.traveler_default_assumption)

    preferences = [kw for kw in QP_RULES.preference_keywords if kw in query]
    pace = next((v for k, v in QP_RULES.pace_keywords.items() if k in query), None)

    elapsed = (time.perf_counter() - t0) * 1000
    logger.info(f"extract_node: destination={destination}, days={days_count}, "
                f"budget={total_budget}, missing_p0={missing_p0}, elapsed={elapsed:.1f}ms")

    return {
        "destination": destination,
        "days_count": days_count,
        "total_budget": total_budget,
        "traveler_type": traveler_type,
        "preferences": preferences,
        "pace": pace,
        "assumptions": assumptions,
        "missing_p0": missing_p0,
        "perf": {**state.get("perf", {}), "extract_ms": elapsed},
    }


async def early_exit_node(state: TravelDraftState) -> dict:
    """Return a prompt for missing P0 fields without running pipeline or LLM."""
    missing = state.get("missing_p0", [])
    return {
        "final_itinerary": None,
        "explanation": None,
        "final_text": DRAFT_CONFIG.missing_p0_template.format(
            missing_fields="、".join(missing)
        ),
    }


async def recall_node(state: TravelDraftState) -> dict:
    """Node 2: Run QP -> Recall -> Rank -> Filter -> Evidence pipeline."""
    t0 = time.perf_counter()

    pipeline_result: PipelineResult | None = None
    recall_degraded = False
    recall_geo_index: dict = {}
    try:
        qp, recall_svc, scorer, flt, eb = _get_pipeline()
        qp_output = qp.process(state["query"])
        recall_result = await recall_svc.recall_from_qp(qp_output)

        for rc in recall_result.candidates:
            c = rc.candidate if hasattr(rc, "candidate") else rc
            title = (c.title or "").strip().lower()
            if not title:
                continue
            lat = c.extra.get("lat")
            lng = c.extra.get("lng")
            photos = c.extra.get("photos") or []
            image_url = c.extra.get("thumbnail") or (photos[0] if photos else None)
            entry: dict = {}
            if lat is not None and lng is not None:
                entry["lat"] = float(lat)
                entry["lng"] = float(lng)
            if image_url:
                entry["image_url"] = str(image_url)
            if entry:
                recall_geo_index[title] = entry

        ranked = scorer.rank_from_qp(recall_result.candidates, qp_output, top_k=15)
        filter_result = flt.apply_from_qp(ranked, qp_output)
        pipeline_result = eb.build(filter_result, recall_result)
        recall_degraded = pipeline_result.degraded

        logger.info(
            f"Pipeline completed: "
            f"recalled={len(recall_result.candidates)}, "
            f"ranked={len(ranked)}, "
            f"accepted={len(filter_result.accepted)}, "
            f"evidence={len(pipeline_result.evidence)}, "
            f"coverage={pipeline_result.coverage:.2f}, "
            f"degraded={pipeline_result.degraded}, "
            f"geo_entries={len(recall_geo_index)}"
        )
        if pipeline_result.assumptions:
            logger.info(f"Pipeline assumptions: {pipeline_result.assumptions}")
    except Exception as exc:
        logger.warning(f"Pipeline failed, will proceed with LLM-only: {exc}")
        recall_degraded = True

    elapsed = (time.perf_counter() - t0) * 1000
    return {
        "pipeline_result": pipeline_result,
        "recall_degraded": recall_degraded,
        "recall_geo_index": recall_geo_index,
        "perf": {**state.get("perf", {}), "recall_ms": elapsed},
    }


async def llm_draft_node(state: TravelDraftState) -> dict:
    """Node 3: Call LLM to generate the itinerary draft."""
    t0 = time.perf_counter()
    t_first_token = None

    destination = state["destination"]
    days_count = state["days_count"]
    total_budget = state["total_budget"]
    traveler_type = state.get("traveler_type")
    preferences = state.get("preferences", [])
    pace = state.get("pace")
    assumptions = list(state.get("assumptions", []))
    pipeline_result = state.get("pipeline_result")

    itinerary_dict = None
    explanation = None

    try:
        llm = _get_llm()
        user_prompt = TRAVEL_DRAFT_USER_PROMPT_TEMPLATE.format(
            destination_city=destination,
            days=days_count,
            budget=int(total_budget),
            traveler_type=traveler_type or "通用休闲",
            preferences="、".join(preferences) if preferences else "无特别偏好",
            pace=pace or "适中",
        )

        candidates_section = _format_candidates_for_prompt(pipeline_result)
        if candidates_section:
            user_prompt += candidates_section
            logger.info(f"Injected candidates into LLM prompt")

        messages = [
            {"role": "system", "content": TRAVEL_DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        logger.info(f"Calling LLM for travel draft: {destination} {days_count}天 预算{int(total_budget)}")

        buffer = ""
        async for chunk in llm.astream(messages):
            if chunk.content:
                if t_first_token is None:
                    t_first_token = time.perf_counter()
                buffer += chunk.content
        raw_content = buffer

        itinerary = _parse_llm_itinerary(
            raw=raw_content,
            destination=destination,
            days_count=days_count,
            total_budget=total_budget,
            traveler_type=traveler_type,
            preferences=preferences,
            assumptions=assumptions,
        )
        explanation = (
            f"已为你生成 {destination} {days_count} 天行程草案"
            f"（预算 {int(total_budget)} 元"
            f"{'，' + traveler_type if traveler_type else ''}"
            f"{'，偏好 ' + '、'.join(preferences) if preferences else ''}"
            f"）。"
        )
        itinerary_dict = itinerary.model_dump(mode="json")
        logger.info("LLM travel draft generated successfully")

    except Exception as e:
        logger.warning(f"LLM draft generation failed, falling back to template: {e}")
        assumptions.append(f"LLM 生成失败（{type(e).__name__}），已降级为模板草案。")
        itinerary = _build_template_itinerary(
            destination=destination,
            days_count=days_count,
            total_budget=total_budget,
            traveler_type=traveler_type,
            assumptions=assumptions,
        )
        explanation = DRAFT_CONFIG.explanation_template.format(days=days_count)
        if assumptions:
            explanation = f"{explanation} {' '.join(assumptions)}".strip()
        itinerary_dict = itinerary.model_dump(mode="json")

    elapsed = (time.perf_counter() - t0) * 1000
    ttft = (t_first_token - t0) * 1000 if t_first_token else None
    return {
        "itinerary": itinerary_dict,
        "explanation": explanation,
        "assumptions": assumptions,
        "perf": {**state.get("perf", {}), "llm_ms": elapsed, "llm_ttft_ms": ttft},
    }


async def postprocess_node(state: TravelDraftState) -> dict:
    """Node 4: Attach evidence, link refs, compute coverage."""
    t0 = time.perf_counter()

    itinerary_dict = state.get("itinerary")
    pipeline_result = state.get("pipeline_result")
    explanation = state.get("explanation")

    if not itinerary_dict:
        return {
            "final_itinerary": None,
            "explanation": explanation,
            "final_text": "未能生成结构化草案，请补充目的地、天数和预算后重试。",
        }

    itinerary = ItineraryV1(**itinerary_dict)

    try:
        _, _, _, _, eb = _get_pipeline()
    except Exception:
        eb = None
    recall_geo = state.get("recall_geo_index") or {}
    _postprocess_with_pipeline(itinerary, pipeline_result, eb, recall_geo)

    elapsed = (time.perf_counter() - t0) * 1000
    return {
        "final_itinerary": itinerary.model_dump(mode="json"),
        "explanation": explanation,
        "final_text": None,
        "perf": {**state.get("perf", {}), "postprocess_ms": elapsed},
    }


# ===================================================================
# Conditional routing
# ===================================================================

def _should_continue_after_extract(state: TravelDraftState) -> str:
    """Route to early_exit if P0 fields are missing, otherwise continue."""
    if state.get("missing_p0"):
        return "early_exit_node"
    return "recall_node"


# ===================================================================
# Graph assembly
# ===================================================================

builder = StateGraph(TravelDraftState, input_schema=TravelDraftInput)

builder.add_node("extract_node", extract_node)
builder.add_node("early_exit_node", early_exit_node)
builder.add_node("recall_node", recall_node)
builder.add_node("llm_draft_node", llm_draft_node)
builder.add_node("postprocess_node", postprocess_node)

builder.add_edge(START, "extract_node")
builder.add_conditional_edges("extract_node", _should_continue_after_extract, {
    "early_exit_node": "early_exit_node",
    "recall_node": "recall_node",
})
builder.add_edge("early_exit_node", END)
builder.add_edge("recall_node", "llm_draft_node")
builder.add_edge("llm_draft_node", "postprocess_node")
builder.add_edge("postprocess_node", END)

travel_draft_graph = builder.compile()
