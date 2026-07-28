from __future__ import annotations

from app.schemas.itinerary_v1 import BudgetSummary, ItineraryDay, ItinerarySlot, ItineraryV1, TripProfile
from app.services.itinerary_planner import ConstraintAwareItineraryPlanner, apply_plan_skeleton, plan_slots_as_payloads
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import ScoredCandidate


def _candidate(
    title: str,
    *,
    score: float,
    lat: float,
    lng: float,
    cost: float = 30,
    tags: list[str] | None = None,
    snippet: str = "",
    candidate_id: str | None = None,
) -> ScoredCandidate:
    candidate = ProviderCandidate(
        candidate_id=candidate_id or f"poi-{title}",
        source="fixture",
        title=title,
        snippet=snippet or f"{title} 文化体验",
        score=score,
        tags=tags or ["文化"],
        extra={
            "lat": lat,
            "lng": lng,
            "cost_estimate": cost,
            "rating": 4.7,
            "address": f"{title}地址",
            "photos": [f"https://example.com/{title}.jpg"],
        },
    )
    return ScoredCandidate(candidate=candidate, total_score=score)


def _two_cluster_candidates() -> list[ScoredCandidate]:
    return [
        _candidate("老城博物馆", score=0.98, lat=31.230, lng=121.470, tags=["文化", "博物馆", "室内"]),
        _candidate("老城艺术馆", score=0.95, lat=31.232, lng=121.472, tags=["文化", "艺术", "室内"]),
        _candidate("老城书店", score=0.92, lat=31.228, lng=121.475, tags=["文化", "书店", "室内"]),
        _candidate("滨江展馆", score=0.91, lat=31.126, lng=121.602, tags=["文化", "展馆", "室内"]),
        _candidate("滨江美术馆", score=0.89, lat=31.129, lng=121.604, tags=["文化", "美术馆", "室内"]),
        _candidate("滨江剧院", score=0.87, lat=31.131, lng=121.606, tags=["文化", "剧院", "室内"]),
    ]


def test_planner_builds_unique_compact_two_day_plan():
    result = ConstraintAwareItineraryPlanner().plan(
        _two_cluster_candidates(),
        destination="上海",
        days=2,
        total_budget=3000,
        preferences=["文化"],
        pace="moderate",
    )

    assert result.feasible is True
    assert result.skeleton is not None
    selections = result.skeleton.selections
    assert len(selections) == 6
    assert len({selection.candidate_id for selection in selections}) == 6
    assert [len(day.selections) for day in result.skeleton.days] == [3, 3]
    assert all(
        selection.distance_from_previous_km is None or selection.distance_from_previous_km <= 18
        for selection in selections
    )
    assert result.elapsed_ms < 200


def test_planner_filters_generic_and_locked_candidates_for_local_replan():
    candidates = [
        _candidate("自由活动", score=1.0, lat=31.23, lng=121.47),
        _candidate("锁定博物馆", score=0.99, lat=31.23, lng=121.47, tags=["室内", "文化"]),
        _candidate("城市博物馆", score=0.95, lat=31.231, lng=121.471, tags=["室内", "博物馆"]),
        _candidate("当代艺术馆", score=0.92, lat=31.232, lng=121.472, tags=["室内", "艺术"]),
        _candidate("历史图书馆", score=0.90, lat=31.233, lng=121.473, tags=["室内", "图书馆"]),
    ]

    result = ConstraintAwareItineraryPlanner().plan(
        candidates,
        destination="上海",
        days=1,
        total_budget=1000,
        constraints=["indoor"],
        excluded_titles=["锁定博物馆"],
        day_indexes=[2],
        slots_per_day=3,
    )

    assert result.feasible is True
    assert result.skeleton is not None
    assert [selection.title for selection in result.skeleton.selections] == [
        "城市博物馆",
        "当代艺术馆",
        "历史图书馆",
    ]
    assert result.rejected_reason_counts["generic_or_low_quality"] == 1
    assert result.rejected_reason_counts["locked_day_duplicate"] == 1
    assert result.skeleton.days[0].day_index == 2


def test_planner_accepts_english_indoor_candidate_terms():
    candidates = [
        _candidate(
            "Science Centre",
            score=0.95,
            lat=69.681,
            lng=18.973,
            tags=["indoor", "museum", "culture"],
            snippet="Indoor science museum",
        ),
        _candidate(
            "Perspektivet Museum",
            score=0.93,
            lat=69.651,
            lng=18.958,
            tags=["indoor", "museum", "culture"],
            snippet="Indoor cultural museum",
        ),
    ]

    result = ConstraintAwareItineraryPlanner().plan(
        candidates,
        destination="Tromso",
        days=1,
        total_budget=1000,
        constraints=["indoor"],
        day_indexes=[2],
        slots_per_day=1,
    )

    assert result.feasible is True
    assert result.skeleton is not None
    assert len(result.skeleton.selections) == 1


def test_planner_returns_explicit_infeasible_result_when_unique_candidates_are_short():
    result = ConstraintAwareItineraryPlanner().plan(
        _two_cluster_candidates()[:2],
        destination="上海",
        days=3,
        total_budget=3000,
    )

    assert result.feasible is False
    assert result.reason == "insufficient_unique_candidates"


def test_planner_respects_daily_poi_budget_before_selecting_high_cost_candidate():
    candidates = [
        _candidate("昂贵主题乐园", score=0.99, lat=31.23, lng=121.47, cost=900),
        _candidate("城市博物馆", score=0.93, lat=31.231, lng=121.471, cost=40),
        _candidate("历史街区", score=0.91, lat=31.232, lng=121.472, cost=30),
    ]

    result = ConstraintAwareItineraryPlanner().plan(
        candidates,
        destination="上海",
        days=1,
        total_budget=1000,
        slots_per_day=2,
    )

    assert result.feasible is True
    assert result.skeleton is not None
    assert "昂贵主题乐园" not in [selection.title for selection in result.skeleton.selections]


def test_planner_deduplicates_same_poi_returned_by_different_providers():
    result = ConstraintAwareItineraryPlanner().plan(
        [
            _candidate("城市博物馆", score=0.99, lat=31.23, lng=121.47, candidate_id="amap-museum"),
            _candidate("城市博物馆", score=0.98, lat=31.23, lng=121.47, candidate_id="search-museum"),
            _candidate("当代艺术馆", score=0.95, lat=31.231, lng=121.471),
            _candidate("历史图书馆", score=0.93, lat=31.232, lng=121.472),
        ],
        destination="上海",
        days=1,
        total_budget=1000,
        slots_per_day=3,
    )

    assert result.feasible is True
    assert result.skeleton is not None
    assert [selection.title for selection in result.skeleton.selections].count("城市博物馆") == 1
    assert result.rejected_reason_counts["duplicate_candidate"] == 1


def test_apply_plan_skeleton_forces_verified_pois_and_keeps_llm_copy_only():
    planner_result = ConstraintAwareItineraryPlanner().plan(
        _two_cluster_candidates()[:3],
        destination="上海",
        days=1,
        total_budget=1000,
        slots_per_day=3,
    )
    assert planner_result.skeleton is not None
    itinerary = ItineraryV1(
        itinerary_id="itinerary-1",
        revision_id="revision-1",
        trip_profile=TripProfile(destination_city="上海"),
        days=[
            ItineraryDay(
                day_index=1,
                theme="LLM主题",
                slots=[
                    ItinerarySlot(slot="上午", activity="LLM 文案", place="东京塔"),
                    ItinerarySlot(slot="下午", activity="LLM 文案", place="埃菲尔铁塔"),
                    ItinerarySlot(slot="晚上", activity="LLM 文案", place="自由活动"),
                ],
            )
        ],
        budget_summary=BudgetSummary(total_estimate=1000),
    )

    result = apply_plan_skeleton(itinerary, planner_result.skeleton)

    assert {slot.place for slot in result.days[0].slots} == {
        "老城博物馆",
        "老城艺术馆",
        "老城书店",
    }
    assert result.days[0].slots[0].activity == "LLM 文案"
    assert all(slot.location is not None for slot in result.days[0].slots)
    assert len(plan_slots_as_payloads(planner_result.skeleton, 1)) == 3
