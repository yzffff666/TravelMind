"""Candidate-driven day-level itinerary replanning.

This service upgrades REPLAN_DAY edits from a static template fallback into
the same recall/ranking decision path used by the draft pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import ROOT_DIR, settings
from app.services.candidate_publishability import evaluate_candidate_publishability
from app.services.destination_grounding import DestinationResolver
from app.services.itinerary_planner import (
    SLOT_LABELS,
    ConstraintAwareItineraryPlanner,
    plan_slots_as_payloads,
)
from app.services.poi_name_match import is_verified_poi_name_match
from app.services.poi_ranking_policy import (
    POIRankingPolicy,
    apply_learned_ranking,
    select_runtime_ranking,
)
from app.services.providers.base import ProviderCallContext
from app.services.ranking_scorer import RankingScorer
from app.services.recall_service import RecallResult, RecallService


@dataclass
class DayReplanReport:
    applied_days: list[int] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    diff_items: list[str] = field(default_factory=list)
    candidate_counts: dict[int, int] = field(default_factory=dict)
    grounding_statuses: dict[int, str] = field(default_factory=dict)
    planner_statuses: dict[int, str] = field(default_factory=dict)


_MIN_CANDIDATES = 2
_CONSTRAINT_TERMS: dict[str, tuple[str, ...]] = {
    "indoor": ("室内", "博物馆", "美术馆", "展馆", "购物中心", "文化"),
    "relaxed": ("轻松", "慢节奏", "咖啡馆", "公园", "休闲"),
    "food": ("美食", "小吃", "餐厅", "夜市", "茶餐厅"),
    "culture": ("文化", "历史", "博物馆", "艺术", "街区"),
}
class DayReplanService:
    """Replan target days using provider candidates and ranking scores."""

    def __init__(
        self,
        *,
        recall_service: RecallService | None = None,
        ranking_scorer: RankingScorer | None = None,
        destination_resolver: DestinationResolver | None = None,
        planner: ConstraintAwareItineraryPlanner | None = None,
        min_candidates: int = _MIN_CANDIDATES,
    ) -> None:
        self._recall_service = recall_service or RecallService(include_mock_fallback=True)
        self._ranking_scorer = ranking_scorer or RankingScorer()
        self._destination_resolver = destination_resolver or DestinationResolver()
        self._planner = planner or ConstraintAwareItineraryPlanner()
        self._min_candidates = max(1, min_candidates)

    async def replan_days(
        self,
        itinerary: dict[str, Any],
        replan_requests: list[dict[str, Any]],
        *,
        context: ProviderCallContext | None = None,
    ) -> DayReplanReport:
        report = DayReplanReport()
        if not replan_requests:
            return report

        for request in replan_requests:
            day_index = request.get("day_index")
            if not isinstance(day_index, int):
                continue
            day = _find_day(itinerary, day_index)
            if day is None:
                report.assumptions.append(f"未找到第{day_index}天，候选重规划已跳过。")
                continue

            constraints = [str(c) for c in (request.get("constraints") or []) if c]
            explicit_place = str(request.get("explicit_place") or "").strip() or None
            target_slot = _normalize_slot(request.get("target_slot"))
            if target_slot and not any(_normalize_slot(slot.get("slot")) == target_slot for slot in day.get("slots") or []):
                report.assumptions.append(f"第{day_index}天未找到{target_slot}时段，已保留原行程。")
                continue
            if explicit_place and not target_slot:
                report.planner_statuses[day_index] = "explicit_place_requires_slot"
                report.assumptions.append(
                    f"请说明要把第{day_index}天的哪个时段换成“{explicit_place}”，已保留原行程。"
                )
                continue
            target_slots = [target_slot] if target_slot else list(SLOT_LABELS)
            required_count = len(target_slots)
            destination = _destination_city(itinerary)
            profile = await self._destination_resolver.resolve(destination)
            if not profile.resolved:
                report.grounding_statuses[day_index] = "unresolved"
                report.assumptions.append(
                    f"第{day_index}天未能可靠定位“{destination}”，已保留原行程，避免混入其他城市候选。"
                )
                continue
            report.grounding_statuses[day_index] = "static" if not profile.is_dynamic else "grounded"
            preferences = _user_preferences(itinerary)
            terms = _query_terms(constraints, preferences)
            query_terms = [explicit_place] if explicit_place else terms
            query = " ".join([profile.canonical_name, *query_terms]).strip() or profile.canonical_name

            recall_result = await self._recall_service.recall_simple(
                query=query,
                city=profile.canonical_name,
                preferences=terms,
                context=context,
            )
            report.assumptions.extend(recall_result.assumptions)
            publishability = evaluate_candidate_publishability(
                recall_result.candidates,
                profile,
                required_count=required_count,
                allow_mock=settings.ALLOW_MOCK_PUBLISH,
            )
            recall_result.candidates = publishability.accepted
            report.candidate_counts[day_index] = len(recall_result.candidates)
            if not publishability.ready:
                report.grounding_statuses[day_index] = publishability.status
                if explicit_place:
                    report.assumptions.append(
                        f"第{day_index}天未找到与“{explicit_place}”位于“{profile.canonical_name}”的可验证地点，已保留原行程。"
                    )
                else:
                    report.assumptions.append(
                        f"第{day_index}天候选不足：仅找到 {len(recall_result.candidates)} 个可验证本地候选，已保留原行程。"
                    )
                continue
            if explicit_place:
                recall_result.candidates = [
                    candidate
                    for candidate in recall_result.candidates
                    if is_verified_poi_name_match(explicit_place, candidate.title)
                ]
                report.candidate_counts[day_index] = len(recall_result.candidates)
                if not recall_result.candidates:
                    report.planner_statuses[day_index] = "explicit_place_unverified"
                    report.assumptions.append(
                        f"第{day_index}天未找到与“{explicit_place}”名称相符且位于“{profile.canonical_name}”的可验证地点，已保留原行程。"
                    )
                    continue

            legacy_ranked = self._ranking_scorer.rank(
                recall_result.candidates,
                preferences=terms,
                budget=_total_budget(itinerary),
                days=len(itinerary.get("days") or []),
                top_k=12,
            )
            policy_ranked = []
            if settings.POI_RANKING_MODE != "legacy":
                policy_ranked = POIRankingPolicy().rank(
                    recall_result.candidates,
                    destination=profile.canonical_name,
                    destination_profile=profile,
                    preferences=terms,
                    budget=_total_budget(itinerary),
                    days=len(itinerary.get("days") or []),
                    top_k=max(12, len(recall_result.candidates)),
                    include_rejected=True,
                    allow_mock=settings.ALLOW_MOCK_PUBLISH,
                )
                model_path = Path(settings.POI_LEARNED_RANKING_MODEL_PATH)
                if not model_path.is_absolute():
                    model_path = ROOT_DIR / model_path
                policy_ranked, _learned_diagnostics = apply_learned_ranking(
                    policy_ranked,
                    mode=settings.POI_LEARNED_RANKING_MODE,
                    model_path=model_path,
                )
            ranked = select_runtime_ranking(
                settings.POI_RANKING_MODE,
                legacy_ranked,
                policy_ranked,
            )
            plan_result = self._planner.plan(
                ranked,
                destination=destination,
                days=1,
                total_budget=_daily_budget(itinerary),
                preferences=terms,
                pace="relaxed" if "relaxed" in constraints else "moderate",
                constraints=() if explicit_place else constraints,
                # An explicit user command may intentionally reuse a POI that
                # appears elsewhere. Candidate title verification and the
                # destination gate remain mandatory.
                excluded_titles=() if explicit_place else _locked_places(itinerary, day_index, target_slot=target_slot),
                anchor_location=_anchor_location(request),
                day_indexes=[day_index],
                slots_per_day=required_count,
            )
            report.planner_statuses[day_index] = "planned" if plan_result.feasible else "infeasible"
            selected_count = len(plan_result.skeleton.selections) if plan_result.skeleton else 0
            report.candidate_counts[day_index] = selected_count

            if not plan_result.feasible or selected_count < required_count:
                report.assumptions.append(
                    f"第{day_index}天候选不足或无法组成满足约束的计划（{selected_count} 个），已保留原行程。"
                )
                continue

            planned_slots = plan_slots_as_payloads(
                plan_result.skeleton,
                day_index,
                slot_labels=target_slots,
            )
            if len(planned_slots) != required_count:
                report.assumptions.append(f"第{day_index}天候选计划缺少目标时段，已保留原行程。")
                continue
            if target_slot:
                planned = planned_slots[0]
                day["slots"] = [
                    planned if _normalize_slot(slot.get("slot")) == target_slot else slot
                    for slot in day.get("slots") or []
                ]
            else:
                day["theme"] = plan_result.skeleton.days[0].theme
                day["slots"] = planned_slots
            report.applied_days.append(day_index)
            scope = f"{target_slot}时段" if target_slot else ""
            report.diff_items.append(
                (
                    f"第{day_index}天{scope}已替换为已验证地点“{explicit_place}”（候选{selected_count}个，来源召回排序）。"
                    if explicit_place
                    else f"第{day_index}天{scope}已基于共享约束规划器重新规划（候选{selected_count}个，来源召回排序）。"
                )
            )

        _dedupe_preserve_order(report.assumptions)
        return report


def _find_day(itinerary: dict[str, Any], day_index: int) -> dict[str, Any] | None:
    for day in itinerary.get("days") or []:
        if day.get("day_index") == day_index:
            return day
    return None


def _destination_city(itinerary: dict[str, Any]) -> str:
    profile = itinerary.get("trip_profile") or {}
    destination = (profile.get("destination_city") or "").strip()
    return destination or "当地"


def _user_preferences(itinerary: dict[str, Any]) -> list[str]:
    profile = itinerary.get("trip_profile") or {}
    constraints = profile.get("constraints") or {}
    prefs = constraints.get("preferences") or []
    return [str(p).strip() for p in prefs if str(p).strip()]


def _total_budget(itinerary: dict[str, Any]) -> float | None:
    budget = (itinerary.get("budget_summary") or {}).get("total_estimate")
    if isinstance(budget, (int, float)) and budget > 0:
        return float(budget)
    return None


def _daily_budget(itinerary: dict[str, Any]) -> float | None:
    total = _total_budget(itinerary)
    days = len(itinerary.get("days") or [])
    return total / days if total is not None and days > 0 else total


def _locked_places(itinerary: dict[str, Any], target_day: int, *, target_slot: str | None = None) -> list[str]:
    return [
        str(slot.get("place") or "").strip()
        for day in itinerary.get("days") or []
        for slot in day.get("slots") or []
        if (
            day.get("day_index") != target_day
            or (target_slot is not None and _normalize_slot(slot.get("slot")) != target_slot)
        )
        if str(slot.get("place") or "").strip()
    ]


def _normalize_slot(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    mapping = {
        "上午": "上午",
        "早上": "上午",
        "morning": "上午",
        "下午": "下午",
        "中午": "下午",
        "afternoon": "下午",
        "晚上": "晚上",
        "夜晚": "晚上",
        "evening": "晚上",
        "night": "晚上",
    }
    return mapping.get(normalized)


def _query_terms(constraints: list[str], preferences: list[str]) -> list[str]:
    terms: list[str] = []
    for constraint in constraints:
        terms.extend(_CONSTRAINT_TERMS.get(constraint, (constraint,)))
    terms.extend(preferences)
    return list(dict.fromkeys(term for term in terms if term))


def _anchor_location(request: dict[str, Any]) -> tuple[float, float] | None:
    anchors = request.get("anchor_locations") or []
    coords: list[tuple[float, float]] = []
    for item in anchors:
        if not isinstance(item, dict):
            continue
        lat = _to_float(item.get("lat"))
        lng = _to_float(item.get("lng"))
        if lat is None or lng is None:
            continue
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            coords.append((lat, lng))
    if not coords:
        return None
    return (
        sum(lat for lat, _ in coords) / len(coords),
        sum(lng for _, lng in coords) / len(coords),
    )


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_preserve_order(items: list[str]) -> None:
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        kept.append(item)
    items[:] = kept
