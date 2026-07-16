"""Candidate-driven day-level itinerary replanning.

This service upgrades REPLAN_DAY edits from a static template fallback into
the same recall/ranking decision path used by the draft pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.providers.base import ProviderCallContext, ProviderCandidate
from app.services.ranking_scorer import RankingScorer, ScoredCandidate
from app.services.recall_service import RecallResult, RecallService


@dataclass
class DayReplanReport:
    applied_days: list[int] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    diff_items: list[str] = field(default_factory=list)
    candidate_counts: dict[int, int] = field(default_factory=dict)


_SLOT_LABELS = ("上午", "下午", "晚上")
_MIN_CANDIDATES = 2
_GENERIC_TITLE_TERMS = (
    "自由活动",
    "待定",
    "当地",
    "核心景区",
    "市中心",
    "餐厅",
    "景点",
    "按新偏好",
)
_CONSTRAINT_TERMS: dict[str, tuple[str, ...]] = {
    "indoor": ("室内", "博物馆", "美术馆", "展馆", "购物中心", "文化"),
    "relaxed": ("轻松", "慢节奏", "咖啡馆", "公园", "休闲"),
    "food": ("美食", "小吃", "餐厅", "夜市", "茶餐厅"),
    "culture": ("文化", "历史", "博物馆", "艺术", "街区"),
}
_CONSTRAINT_THEMES = {
    "indoor": "候选驱动的室内体验",
    "relaxed": "候选驱动的轻松慢游",
    "food": "候选驱动的在地美食",
    "culture": "候选驱动的人文探索",
}


class DayReplanService:
    """Replan target days using provider candidates and ranking scores."""

    def __init__(
        self,
        *,
        recall_service: RecallService | None = None,
        ranking_scorer: RankingScorer | None = None,
        min_candidates: int = _MIN_CANDIDATES,
    ) -> None:
        self._recall_service = recall_service or RecallService(include_mock_fallback=True)
        self._ranking_scorer = ranking_scorer or RankingScorer()
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
            destination = _destination_city(itinerary)
            preferences = _user_preferences(itinerary)
            terms = _query_terms(constraints, preferences)
            query = " ".join([destination, *terms]).strip() or destination

            recall_result = await self._recall_service.recall_simple(
                query=query,
                city=destination,
                preferences=terms,
                context=context,
            )
            report.assumptions.extend(recall_result.assumptions)

            ranked = self._ranking_scorer.rank(
                recall_result.candidates,
                preferences=terms,
                budget=_total_budget(itinerary),
                days=len(itinerary.get("days") or []),
                top_k=12,
            )
            selected = _select_candidates(ranked, destination=destination, limit=len(_SLOT_LABELS))
            report.candidate_counts[day_index] = len(selected)

            if len(selected) < self._min_candidates:
                report.assumptions.append(
                    f"第{day_index}天候选不足（{len(selected)} 个），保留规则兜底行程。"
                )
                continue

            fallback_slots = list(day.get("slots") or [])
            day["theme"] = _theme_for_constraints(constraints)
            day["slots"] = _slots_from_candidates(
                selected,
                constraints=constraints,
                fallback_slots=fallback_slots,
            )
            report.applied_days.append(day_index)
            report.diff_items.append(
                f"第{day_index}天已基于候选POI重新规划（候选{len(selected)}个，来源召回排序）。"
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


def _query_terms(constraints: list[str], preferences: list[str]) -> list[str]:
    terms: list[str] = []
    for constraint in constraints:
        terms.extend(_CONSTRAINT_TERMS.get(constraint, (constraint,)))
    terms.extend(preferences)
    return list(dict.fromkeys(term for term in terms if term))


def _select_candidates(
    ranked: list[ScoredCandidate],
    *,
    destination: str,
    limit: int,
) -> list[ScoredCandidate]:
    selected: list[ScoredCandidate] = []
    seen: set[str] = set()
    for scored in ranked:
        title = (scored.candidate.title or "").strip()
        if not title:
            continue
        if _is_generic_title(title, destination):
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        selected.append(scored)
        if len(selected) >= limit:
            break
    return selected


def _is_generic_title(title: str, destination: str) -> bool:
    normalized = title.strip()
    if normalized == destination:
        return True
    if len(normalized) <= 1:
        return True
    return any(term in normalized for term in _GENERIC_TITLE_TERMS)


def _theme_for_constraints(constraints: list[str]) -> str:
    if "indoor" in constraints and "relaxed" in constraints:
        return "候选驱动的轻松室内体验"
    for constraint in constraints:
        if constraint in _CONSTRAINT_THEMES:
            return _CONSTRAINT_THEMES[constraint]
    return "候选驱动的一日重规划"


def _slots_from_candidates(
    selected: list[ScoredCandidate],
    *,
    constraints: list[str],
    fallback_slots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for index, scored in enumerate(selected[: len(_SLOT_LABELS)]):
        candidate = scored.candidate
        slot_label = _SLOT_LABELS[index]
        slot = {
            "slot": slot_label,
            "activity": _activity_text(candidate, slot_label, constraints),
            "place": candidate.title,
            "transit": "公共交通/步行",
            "alternatives": _alternatives(selected, skip_title=candidate.title),
            "evidence_refs": [_evidence_ref(candidate)],
        }
        location = _location(candidate)
        if location:
            slot["location"] = location
        image_url = _image_url(candidate)
        if image_url:
            slot["image_url"] = image_url
        slots.append(slot)
    _fill_missing_slots(slots, fallback_slots or [])
    return slots


def _fill_missing_slots(slots: list[dict[str, Any]], fallback_slots: list[dict[str, Any]]) -> None:
    used_labels = {slot.get("slot") for slot in slots}
    fallback_by_label = {
        slot.get("slot"): slot
        for slot in fallback_slots
        if slot.get("slot") in _SLOT_LABELS
    }
    for label in _SLOT_LABELS:
        if label in used_labels:
            continue
        fallback = dict(fallback_by_label.get(label) or {
            "slot": label,
            "activity": "自由活动",
            "place": None,
            "transit": "公共交通/步行",
        })
        fallback.setdefault("alternatives", [])
        fallback.setdefault("evidence_refs", [])
        slots.append(fallback)
        used_labels.add(label)
    slots.sort(key=lambda slot: _SLOT_LABELS.index(slot.get("slot")) if slot.get("slot") in _SLOT_LABELS else 99)


def _activity_text(candidate: ProviderCandidate, slot_label: str, constraints: list[str]) -> str:
    title = candidate.title
    if "indoor" in constraints:
        suffix = "室内参观" if slot_label != "晚上" else "室内休闲与用餐"
    elif "food" in constraints:
        suffix = "在地美食体验"
    elif "culture" in constraints:
        suffix = "人文参观"
    elif "relaxed" in constraints:
        suffix = "轻松游览"
    else:
        suffix = "游览体验"
    return f"{title}{suffix}"


def _alternatives(selected: list[ScoredCandidate], *, skip_title: str) -> list[dict[str, str]]:
    alternatives: list[dict[str, str]] = []
    for scored in selected:
        title = scored.candidate.title
        if title == skip_title:
            continue
        alternatives.append({
            "title": title,
            "reason": f"候选排序分 {scored.total_score:.2f}",
        })
        if len(alternatives) >= 2:
            break
    return alternatives


def _evidence_ref(candidate: ProviderCandidate) -> str:
    return f"{candidate.source}:{candidate.candidate_id}"


def _location(candidate: ProviderCandidate) -> dict[str, float] | None:
    lat = _to_float(candidate.extra.get("lat"))
    lng = _to_float(candidate.extra.get("lng"))
    if lat is None or lng is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return {"lat": lat, "lng": lng}


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _image_url(candidate: ProviderCandidate) -> str | None:
    image_url = candidate.extra.get("image_url")
    if isinstance(image_url, str) and image_url.strip():
        return image_url.strip()
    photos = candidate.extra.get("photos")
    if isinstance(photos, list):
        for photo in photos:
            if isinstance(photo, str) and photo.strip():
                return photo.strip()
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
