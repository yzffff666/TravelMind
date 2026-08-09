"""Constraint-aware POI planning for travel itinerary generation.

The planner is intentionally small and deterministic.  Provider recall and
ranking produce a candidate set; this module selects a compact, non-duplicate
day/slot combination before the LLM writes presentation text.  The same API is
used for create and ``Edit Day N`` flows so they do not drift into separate
decision policies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Iterable

from app.schemas.itinerary_v1 import ItineraryDay, ItinerarySlot, ItineraryV1, Location
from app.services.ranking_scorer import ScoredCandidate


SLOT_LABELS = ("上午", "下午", "晚上")

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
_LOW_QUALITY_TITLE_TERMS = (
    "问询台",
    "售票处",
    "检票口",
    "出入口",
    "停车场",
    "卫生间",
    "游客中心",
    "相亲角",
    "打卡点",
)
_INDOOR_TERMS = (
    "室内",
    "博物馆",
    "美术馆",
    "展馆",
    "展览",
    "艺术馆",
    "艺术宫",
    "艺术中心",
    "文化中心",
    "购物中心",
    "商场",
    "剧院",
    "影院",
    "图书馆",
    "书店",
    "indoor",
    "museum",
    "art gallery",
    "exhibition",
    "library",
    "theatre",
    "theater",
    "cinema",
    "shopping centre",
    "shopping center",
)


@dataclass(frozen=True, slots=True)
class PlannerConfig:
    """Bounded search and feasibility limits for itinerary planning."""

    beam_width: int = 16
    candidate_limit: int = 24
    max_leg_km: float = 18.0
    max_trip_poi_budget_ratio: float = 0.55
    distance_penalty_per_km: float = 0.018
    cost_penalty: float = 0.16
    diversity_bonus: float = 0.08
    slots_by_pace: dict[str, int] = field(
        default_factory=lambda: {"relaxed": 2, "moderate": 3, "intensive": 3}
    )


@dataclass(frozen=True, slots=True)
class PlanSelection:
    day_index: int
    slot: str
    scored: ScoredCandidate
    utility: float
    distance_from_previous_km: float | None
    estimated_cost: float
    reasons: tuple[str, ...]

    @property
    def candidate_id(self) -> str:
        return self.scored.candidate.candidate_id

    @property
    def title(self) -> str:
        return self.scored.candidate.title

    def to_dict(self) -> dict[str, Any]:
        candidate = self.scored.candidate
        lat, lng = _candidate_location(candidate)
        photos = candidate.extra.get("photos") or []
        image_url = candidate.extra.get("image_url") or candidate.extra.get("thumbnail")
        if not image_url and photos:
            image_url = photos[0]
        return {
            "day_index": self.day_index,
            "slot": self.slot,
            "candidate_id": self.candidate_id,
            "place": self.title,
            "source": candidate.source,
            "ranking_score": round(self.scored.total_score, 4),
            "utility": round(self.utility, 4),
            "estimated_cost": round(self.estimated_cost, 2),
            "distance_from_previous_km": (
                round(self.distance_from_previous_km, 3)
                if self.distance_from_previous_km is not None
                else None
            ),
            "reasons": list(self.reasons),
            "tags": list(candidate.tags or []),
            "location": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
            "image_url": str(image_url) if image_url else None,
            "evidence_ref": f"ev-{self.candidate_id}",
        }


@dataclass(frozen=True, slots=True)
class PlanDay:
    day_index: int
    theme: str
    selections: tuple[PlanSelection, ...]
    estimated_cost: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "day_index": self.day_index,
            "theme": self.theme,
            "estimated_cost": round(self.estimated_cost, 2),
            "slots": [selection.to_dict() for selection in self.selections],
        }


@dataclass(frozen=True, slots=True)
class PlanSkeleton:
    destination: str
    days: tuple[PlanDay, ...]
    slots_per_day: int
    total_utility: float
    estimated_poi_cost: float
    constraints: tuple[str, ...]
    preferences: tuple[str, ...]

    @property
    def selections(self) -> tuple[PlanSelection, ...]:
        return tuple(selection for day in self.days for selection in day.selections)

    @property
    def selected_candidates(self) -> list[ScoredCandidate]:
        return [selection.scored for selection in self.selections]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "plan_skeleton.v1",
            "destination": self.destination,
            "slots_per_day": self.slots_per_day,
            "total_utility": round(self.total_utility, 4),
            "estimated_poi_cost": round(self.estimated_poi_cost, 2),
            "constraints": list(self.constraints),
            "preferences": list(self.preferences),
            "days": [day.to_dict() for day in self.days],
        }


@dataclass(frozen=True, slots=True)
class PlannerResult:
    feasible: bool
    skeleton: PlanSkeleton | None = None
    reason: str | None = None
    candidate_count: int = 0
    eligible_count: int = 0
    rejected_reason_counts: dict[str, int] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "feasible": self.feasible,
            "reason": self.reason,
            "candidate_count": self.candidate_count,
            "eligible_count": self.eligible_count,
            "rejected_reason_counts": dict(self.rejected_reason_counts),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "skeleton": self.skeleton.to_dict() if self.skeleton else None,
        }


@dataclass(frozen=True, slots=True)
class _BeamState:
    selections: tuple[PlanSelection, ...]
    used_keys: frozenset[str]
    score: float
    day_costs: tuple[float, ...]


class ConstraintAwareItineraryPlanner:
    """Select a compact and feasible candidate plan with bounded beam search."""

    def __init__(self, config: PlannerConfig | None = None) -> None:
        self._config = config or PlannerConfig()

    def plan(
        self,
        candidates: list[ScoredCandidate],
        *,
        destination: str,
        days: int,
        total_budget: float | None,
        preferences: Iterable[str] | None = None,
        pace: str | None = None,
        constraints: Iterable[str] | None = None,
        excluded_titles: Iterable[str] | None = None,
        anchor_location: tuple[float, float] | None = None,
        day_indexes: list[int] | None = None,
        slots_per_day: int | None = None,
    ) -> PlannerResult:
        """Return a feasible day/slot plan, or an explicit reason not to publish one."""
        import time

        started = time.perf_counter()
        normalized_constraints = tuple(_normalize_constraint(value) for value in (constraints or []) if value)
        normalized_constraints = tuple(dict.fromkeys(value for value in normalized_constraints if value))
        normalized_preferences = tuple(str(value).strip() for value in (preferences or []) if str(value).strip())
        normalized_exclusions = {_normalize_title(value) for value in (excluded_titles or []) if value}
        if days < 1:
            return self._infeasible("invalid_days", len(candidates), 0, {}, started)

        indexes = list(day_indexes or range(1, days + 1))
        if len(indexes) != days or len(set(indexes)) != days:
            return self._infeasible("invalid_day_indexes", len(candidates), 0, {}, started)

        eligible, rejected = self._eligible_candidates(
            candidates,
            destination=destination,
            constraints=normalized_constraints,
            excluded_titles=normalized_exclusions,
        )
        if len(eligible) < days:
            return self._infeasible("insufficient_unique_candidates", len(candidates), len(eligible), rejected, started)

        slot_count = self._slots_per_day(
            candidate_count=len(eligible),
            days=days,
            pace=pace,
            requested=slots_per_day,
        )
        if slot_count < 1:
            return self._infeasible("insufficient_candidates", len(candidates), len(eligible), rejected, started)

        total_slots = days * slot_count
        daily_poi_budget = self._daily_poi_budget(total_budget, days)
        beam: list[_BeamState] = [
            _BeamState(selections=(), used_keys=frozenset(), score=0.0, day_costs=tuple(0.0 for _ in indexes))
        ]

        for step in range(total_slots):
            day_position = step // slot_count
            day_index = indexes[day_position]
            slot_label = SLOT_LABELS[step % slot_count]
            next_beam: list[_BeamState] = []
            for state in beam:
                current_day = [selection for selection in state.selections if selection.day_index == day_index]
                previous_location = _candidate_location(current_day[-1].scored.candidate) if current_day else anchor_location
                current_tags = {tag.lower() for selection in current_day for tag in selection.scored.candidate.tags}
                for scored in eligible:
                    candidate = scored.candidate
                    key = _candidate_key(scored)
                    if key in state.used_keys:
                        continue
                    estimated_cost = _candidate_cost(scored)
                    if (
                        daily_poi_budget is not None
                        and state.day_costs[day_position] + estimated_cost > daily_poi_budget
                    ):
                        continue
                    distance = _distance_from(previous_location, _candidate_location(candidate))
                    if distance is not None and distance > self._config.max_leg_km:
                        continue
                    utility, reasons = self._utility(
                        scored,
                        estimated_cost=estimated_cost,
                        daily_budget=daily_poi_budget,
                        distance_km=distance,
                        current_tags=current_tags,
                        preferences=normalized_preferences,
                    )
                    selection = PlanSelection(
                        day_index=day_index,
                        slot=slot_label,
                        scored=scored,
                        utility=utility,
                        distance_from_previous_km=distance,
                        estimated_cost=estimated_cost,
                        reasons=tuple(reasons),
                    )
                    day_costs = list(state.day_costs)
                    day_costs[day_position] += estimated_cost
                    next_beam.append(
                        _BeamState(
                            selections=(*state.selections, selection),
                            used_keys=state.used_keys | {key},
                            score=state.score + utility,
                            day_costs=tuple(day_costs),
                        )
                    )
            if not next_beam:
                # Candidate density can be too sparse for the requested pace
                # even when every candidate is individually valid. For create
                # flows, reduce density before rejecting the whole trip; explicit
                # local-replan requests keep their requested slot count strict.
                if slots_per_day is None and slot_count > 1:
                    return self.plan(
                        candidates,
                        destination=destination,
                        days=days,
                        total_budget=total_budget,
                        preferences=normalized_preferences,
                        pace=pace,
                        constraints=normalized_constraints,
                        excluded_titles=normalized_exclusions,
                        anchor_location=anchor_location,
                        day_indexes=indexes,
                        slots_per_day=slot_count - 1,
                    )
                return self._infeasible(
                    f"no_feasible_candidate_for_day_{day_index}_{slot_label}",
                    len(candidates),
                    len(eligible),
                    rejected,
                    started,
                )
            next_beam.sort(key=lambda item: item.score, reverse=True)
            beam = next_beam[: self._config.beam_width]

        best = beam[0]
        plan_days = tuple(
            PlanDay(
                day_index=day_index,
                theme=_theme_for(day_index, normalized_constraints, normalized_preferences),
                selections=tuple(selection for selection in best.selections if selection.day_index == day_index),
                estimated_cost=best.day_costs[position],
            )
            for position, day_index in enumerate(indexes)
        )
        skeleton = PlanSkeleton(
            destination=destination,
            days=plan_days,
            slots_per_day=slot_count,
            total_utility=best.score,
            estimated_poi_cost=sum(best.day_costs),
            constraints=normalized_constraints,
            preferences=normalized_preferences,
        )
        return PlannerResult(
            feasible=True,
            skeleton=skeleton,
            candidate_count=len(candidates),
            eligible_count=len(eligible),
            rejected_reason_counts=rejected,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def _eligible_candidates(
        self,
        candidates: list[ScoredCandidate],
        *,
        destination: str,
        constraints: tuple[str, ...],
        excluded_titles: set[str],
    ) -> tuple[list[ScoredCandidate], dict[str, int]]:
        rejected: dict[str, int] = {}
        seen: set[str] = set()
        eligible: list[ScoredCandidate] = []
        for scored in sorted(candidates, key=lambda item: item.total_score, reverse=True):
            title = (scored.candidate.title or "").strip()
            key = _candidate_key(scored)
            reason: str | None = None
            if not title or _is_generic_title(title, destination):
                reason = "generic_or_low_quality"
            elif key in seen:
                reason = "duplicate_candidate"
            elif _normalize_title(title) in excluded_titles:
                reason = "locked_day_duplicate"
            elif "indoor" in constraints and not _is_indoor(scored):
                reason = "indoor_constraint_mismatch"
            if reason:
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            seen.add(key)
            eligible.append(scored)
            if len(eligible) >= self._config.candidate_limit:
                break
        return eligible, rejected

    def _slots_per_day(self, *, candidate_count: int, days: int, pace: str | None, requested: int | None) -> int:
        if requested is not None:
            target = max(1, min(len(SLOT_LABELS), requested))
        else:
            target = self._config.slots_by_pace.get((pace or "moderate").lower(), 3)
        return min(target, candidate_count // days)

    def _daily_poi_budget(self, total_budget: float | None, days: int) -> float | None:
        if total_budget is None or total_budget <= 0:
            return None
        return total_budget * self._config.max_trip_poi_budget_ratio / days

    def _utility(
        self,
        scored: ScoredCandidate,
        *,
        estimated_cost: float,
        daily_budget: float | None,
        distance_km: float | None,
        current_tags: set[str],
        preferences: tuple[str, ...],
    ) -> tuple[float, list[str]]:
        utility = scored.total_score
        reasons = [f"ranking_score={scored.total_score:.2f}"]
        candidate_tags = {tag.lower() for tag in scored.candidate.tags}
        if candidate_tags - current_tags:
            utility += self._config.diversity_bonus
            reasons.append("day_diversity")
        if distance_km is not None:
            utility -= distance_km * self._config.distance_penalty_per_km
            reasons.append(f"distance={distance_km:.1f}km")
        if daily_budget and estimated_cost:
            utility -= min(estimated_cost / daily_budget, 1.0) * self._config.cost_penalty
            reasons.append(f"cost={estimated_cost:.0f}")
        if _preference_overlap(scored, preferences):
            reasons.append("preference_match")
        return utility, reasons

    @staticmethod
    def _infeasible(
        reason: str,
        candidate_count: int,
        eligible_count: int,
        rejected: dict[str, int],
        started: float,
    ) -> PlannerResult:
        import time

        return PlannerResult(
            feasible=False,
            reason=reason,
            candidate_count=candidate_count,
            eligible_count=eligible_count,
            rejected_reason_counts=rejected,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )


def apply_plan_skeleton(itinerary: ItineraryV1, skeleton: PlanSkeleton) -> ItineraryV1:
    """Force the final itinerary POIs to match the planner's verified decisions.

    LLM output may improve a theme or activity sentence, but it may not add,
    remove, rename, or move selected POIs. This is the last deterministic
    boundary before evidence/backfill post-processing.
    """
    llm_days = {day.day_index: day for day in itinerary.days}
    days: list[ItineraryDay] = []
    for planned_day in skeleton.days:
        llm_day = llm_days.get(planned_day.day_index)
        activity_by_slot = {
            slot.slot: slot.activity
            for slot in (llm_day.slots if llm_day else [])
            if slot.activity and slot.activity.strip()
        }
        slots: list[ItinerarySlot] = []
        for selection in planned_day.selections:
            candidate = selection.scored.candidate
            location = _candidate_location(candidate)
            photos = candidate.extra.get("photos") or []
            image_url = candidate.extra.get("image_url") or candidate.extra.get("thumbnail")
            if not image_url and photos:
                image_url = photos[0]
            slots.append(
                ItinerarySlot(
                    slot=selection.slot,
                    activity=activity_by_slot.get(selection.slot) or _activity_hint(candidate, selection.slot),
                    place=candidate.title,
                    transit="公共交通/步行",
                    location=Location(lat=location[0], lng=location[1]) if location else None,
                    image_url=str(image_url) if image_url else None,
                    evidence_refs=[f"ev-{candidate.candidate_id}"],
                )
            )
        theme = (llm_day.theme if llm_day and llm_day.theme else planned_day.theme)
        days.append(ItineraryDay(day_index=planned_day.day_index, theme=theme, slots=slots))
    itinerary.days = days
    return itinerary


def plan_slots_as_payloads(
    skeleton: PlanSkeleton,
    day_index: int,
    *,
    slot_labels: Iterable[str] | None = None,
    response_language: str | None = None,
) -> list[dict[str, Any]]:
    """Render one planned day for the edit API without depending on an LLM."""
    day = next((item for item in skeleton.days if item.day_index == day_index), None)
    if day is None:
        return []
    requested_slots = list(slot_labels or [])
    if requested_slots and len(requested_slots) != len(day.selections):
        return []
    payloads: list[dict[str, Any]] = []
    for position, selection in enumerate(day.selections):
        candidate = selection.scored.candidate
        location = _candidate_location(candidate)
        photos = candidate.extra.get("photos") or []
        image_url = candidate.extra.get("image_url") or candidate.extra.get("thumbnail")
        if not image_url and photos:
            image_url = photos[0]
        payload: dict[str, Any] = {
            "slot": requested_slots[position] if requested_slots else selection.slot,
            "activity": _activity_hint(
                candidate,
                selection.slot,
                response_language=response_language,
            ),
            "place": candidate.title,
            "transit": "公共交通/步行",
            "alternatives": [],
            "evidence_refs": [f"ev-{candidate.candidate_id}"],
        }
        if location:
            payload["location"] = {"lat": location[0], "lng": location[1]}
        if image_url:
            payload["image_url"] = str(image_url)
        payloads.append(payload)
    return payloads


def _candidate_key(scored: ScoredCandidate) -> str:
    candidate = scored.candidate
    # Provider ids are source-specific. Amap and search can return the same
    # real POI with different ids, so itinerary uniqueness must be keyed by
    # normalized title before falling back to the provider identifier.
    title_key = _normalize_title(candidate.title)
    return f"title:{title_key}" if title_key else f"id:{candidate.candidate_id}"


def _normalize_title(value: str) -> str:
    return "".join(str(value or "").lower().split())


def _candidate_cost(scored: ScoredCandidate) -> float:
    try:
        cost = float(scored.candidate.extra.get("cost_estimate") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, cost)


def _candidate_location(candidate: Any) -> tuple[float, float] | tuple[None, None]:
    try:
        lat = float(candidate.extra.get("lat"))
        lng = float(candidate.extra.get("lng"))
    except (TypeError, ValueError):
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    return lat, lng


def _distance_from(
    left: tuple[float | None, float | None] | None,
    right: tuple[float | None, float | None],
) -> float | None:
    if left is None or None in left or None in right:
        return None
    lat1, lng1 = left
    lat2, lng2 = right
    assert lat1 is not None and lng1 is not None and lat2 is not None and lng2 is not None
    earth_radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return earth_radius * 2 * atan2(sqrt(a), sqrt(1 - a))


def _is_generic_title(title: str, destination: str) -> bool:
    normalized = title.strip()
    return (
        not normalized
        or normalized == destination
        or len(normalized) <= 1
        or any(term in normalized for term in _GENERIC_TITLE_TERMS)
        or any(term in normalized for term in _LOW_QUALITY_TITLE_TERMS)
    )


def _is_indoor(scored: ScoredCandidate) -> bool:
    candidate = scored.candidate
    haystack = " ".join(
        [candidate.title or "", candidate.snippet or "", " ".join(candidate.tags or [])]
    ).lower()
    return any(term in haystack for term in _INDOOR_TERMS)


def _normalize_constraint(value: object) -> str:
    text = str(value).strip().lower()
    mapping = {"室内": "indoor", "轻松": "relaxed", "美食": "food", "文化": "culture"}
    return mapping.get(text, text)


def _preference_overlap(scored: ScoredCandidate, preferences: tuple[str, ...]) -> bool:
    if not preferences:
        return False
    candidate = scored.candidate
    haystack = " ".join([candidate.title or "", candidate.snippet or "", " ".join(candidate.tags or [])]).lower()
    return any(preference.lower() in haystack for preference in preferences)


def _theme_for(day_index: int, constraints: tuple[str, ...], preferences: tuple[str, ...]) -> str:
    if "indoor" in constraints:
        return "候选驱动的室内体验"
    if "relaxed" in constraints:
        return "候选驱动的轻松慢游"
    if preferences:
        return f"{preferences[(day_index - 1) % len(preferences)]}主题探索"
    return "候选驱动的城市探索"


def _activity_hint(candidate: Any, slot: str, *, response_language: str | None = None) -> str:
    if response_language == "en":
        if slot == "晚上":
            return f"Enjoy an evening experience at {candidate.title}"
        return f"Explore {candidate.title}"
    suffix = "游览" if slot != "晚上" else "夜间体验"
    return f"在{candidate.title}{suffix}"
