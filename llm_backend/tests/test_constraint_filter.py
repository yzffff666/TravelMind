"""Tests for T-M2-000d: ConstraintFilter (hard constraint rule chain).

Covers:
- Budget filter (reject over-budget, pass under-budget)
- Pace filter (reject lowest-scored when too many)
- Distance filter (reject far-away POIs)
- Chain execution (all rules run, reasons collected)
- Relaxation (threshold loosened when too few survivors)
- QP integration via apply_from_qp
- Edge cases (empty input, missing fields, no budget)
"""

from app.services.constraint_filter import (
    ConstraintFilter,
    FilterConfig,
    FilterResult,
)
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import RankingScorer, ScoredCandidate


def _make_scored(
    title: str = "测试",
    cost: float = 0.0,
    rating: float = 4.0,
    total_score: float = 0.5,
    lat: float | None = None,
    lng: float | None = None,
    tags: list[str] | None = None,
) -> ScoredCandidate:
    extra = {"cost_estimate": cost, "rating": rating}
    if lat is not None:
        extra["lat"] = lat
    if lng is not None:
        extra["lng"] = lng
    c = ProviderCandidate(
        candidate_id=f"test-{title}",
        source="test",
        title=title,
        tags=tags or ["景点"],
        extra=extra,
    )
    return ScoredCandidate(candidate=c, total_score=total_score, breakdown={})


# ======================== Budget Filter ========================


class TestBudgetFilter:
    def test_over_budget_rejected(self):
        candidates = [_make_scored("贵景点", cost=800, total_score=0.9)]
        flt = ConstraintFilter()
        result = flt.apply(candidates, budget=4000, days=4)
        assert len(result.rejected) == 1
        assert "超出" in result.rejected[0].reject_reasons[0]

    def test_under_budget_accepted(self):
        candidates = [_make_scored("便宜景点", cost=100, total_score=0.8)]
        flt = ConstraintFilter()
        result = flt.apply(candidates, budget=4000, days=4)
        assert len(result.accepted) == 1

    def test_no_budget_skips_filter(self):
        candidates = [_make_scored("任意", cost=9999, total_score=0.8)]
        flt = ConstraintFilter()
        result = flt.apply(candidates, budget=None, days=4)
        assert len(result.accepted) == 1

    def test_free_poi_always_passes(self):
        candidates = [_make_scored("免费公园", cost=0, total_score=0.7)]
        flt = ConstraintFilter()
        result = flt.apply(candidates, budget=2000, days=3)
        assert len(result.accepted) == 1


# ======================== Pace Filter ========================


class TestPaceFilter:
    def test_relaxed_pace_limits_to_3(self):
        candidates = [_make_scored(f"P{i}", total_score=1.0 - i * 0.1) for i in range(5)]
        flt = ConstraintFilter()
        result = flt.apply(candidates, pace="relaxed")
        assert len(result.accepted) == 3

    def test_moderate_pace_limits_to_4(self):
        candidates = [_make_scored(f"P{i}", total_score=1.0 - i * 0.1) for i in range(6)]
        flt = ConstraintFilter()
        result = flt.apply(candidates, pace="moderate")
        assert len(result.accepted) == 4

    def test_intensive_pace_allows_6(self):
        candidates = [_make_scored(f"P{i}", total_score=0.5) for i in range(6)]
        flt = ConstraintFilter()
        result = flt.apply(candidates, pace="intensive")
        assert len(result.accepted) == 6

    def test_pace_rejects_lowest_scored(self):
        high = _make_scored("高分", total_score=0.9)
        low = _make_scored("低分", total_score=0.1)
        mid = _make_scored("中分", total_score=0.5)
        extra = _make_scored("备选", total_score=0.6)
        flt = ConstraintFilter()
        result = flt.apply([low, high, mid, extra], pace="relaxed")
        accepted_titles = {s.candidate.title for s in result.accepted}
        assert "高分" in accepted_titles
        assert "低分" not in accepted_titles

    def test_under_limit_no_rejection(self):
        candidates = [_make_scored(f"P{i}") for i in range(2)]
        flt = ConstraintFilter()
        result = flt.apply(candidates, pace="relaxed")
        assert len(result.accepted) == 2
        assert len(result.rejected) == 0


# ======================== Distance Filter ========================


class TestDistanceFilter:
    def test_far_poi_rejected(self):
        far = _make_scored("远郊", lat=32.0, lng=121.0, total_score=0.8)
        flt = ConstraintFilter()
        result = flt.apply([far], city_center=(31.23, 121.47))
        assert len(result.rejected) == 1
        assert "距离过远" in result.rejected[0].reject_reasons[0]

    def test_near_poi_accepted(self):
        near = _make_scored("市区", lat=31.24, lng=121.48, total_score=0.8)
        flt = ConstraintFilter()
        result = flt.apply([near], city_center=(31.23, 121.47))
        assert len(result.accepted) == 1

    def test_no_coordinates_skipped(self):
        no_coord = _make_scored("无坐标", total_score=0.8)
        flt = ConstraintFilter()
        result = flt.apply([no_coord], city_center=(31.23, 121.47))
        assert len(result.accepted) == 1

    def test_no_city_center_skips_filter(self):
        far = _make_scored("远郊", lat=40.0, lng=116.0, total_score=0.8)
        flt = ConstraintFilter()
        result = flt.apply([far], city_center=None)
        assert len(result.accepted) == 1


# ======================== Chain Execution ========================


class TestChainExecution:
    def test_all_rules_run_and_reasons_collected(self):
        expensive_far = _make_scored("贵且远", cost=800, lat=35.0, lng=121.0, total_score=0.5)
        flt = ConstraintFilter()
        result = flt.apply(
            [expensive_far],
            budget=4000, days=4,
            city_center=(31.23, 121.47),
        )
        assert len(result.rejected) == 1
        reasons = result.rejected[0].reject_reasons
        assert len(reasons) >= 1

    def test_mixed_accept_and_reject(self):
        good = _make_scored("合适", cost=50, lat=31.24, lng=121.48, total_score=0.9)
        bad = _make_scored("不合适", cost=900, lat=35.0, lng=121.0, total_score=0.3)
        flt = ConstraintFilter()
        result = flt.apply(
            [good, bad],
            budget=4000, days=4,
            city_center=(31.23, 121.47),
        )
        assert len(result.accepted) == 1
        assert result.accepted[0].candidate.title == "合适"


# ======================== Relaxation ========================


class TestRelaxation:
    def test_relaxation_when_too_few_survivors(self):
        candidates = [
            _make_scored(f"P{i}", cost=450, total_score=0.9 - i * 0.1)
            for i in range(5)
        ]
        config = FilterConfig(
            budget_ratio_limit=0.3,
            relaxation_budget_ratio=0.8,
            min_survivors=3,
        )
        flt = ConstraintFilter(config)
        result = flt.apply(candidates, budget=4000, days=4)
        assert result.relaxed is True
        assert len(result.assumptions) > 0
        assert len(result.accepted) >= 3

    def test_no_relaxation_when_enough_survivors(self):
        candidates = [
            _make_scored(f"P{i}", cost=50, total_score=0.8)
            for i in range(5)
        ]
        flt = ConstraintFilter()
        result = flt.apply(candidates, budget=4000, days=4, pace="intensive")
        assert result.relaxed is False
        assert len(result.assumptions) == 0


# ======================== QP Integration ========================


class TestApplyFromQP:
    def test_apply_from_qp(self):
        candidates = [
            _make_scored("A", cost=100, total_score=0.9),
            _make_scored("B", cost=800, total_score=0.5),
        ]
        qp_output = {
            "constraints": {
                "budget": 4000.0,
                "days": 4,
                "pace": "moderate",
            }
        }
        flt = ConstraintFilter()
        result = flt.apply_from_qp(candidates, qp_output)
        assert len(result.accepted) >= 1

    def test_apply_from_qp_empty_constraints(self):
        candidates = [_make_scored("X", total_score=0.7)]
        flt = ConstraintFilter()
        result = flt.apply_from_qp(candidates, {})
        assert len(result.accepted) == 1


# ======================== Edge Cases ========================


class TestEdgeCases:
    def test_empty_candidates(self):
        flt = ConstraintFilter()
        result = flt.apply([])
        assert result.accepted == []
        assert result.rejected == []

    def test_single_candidate_accepted(self):
        flt = ConstraintFilter()
        result = flt.apply([_make_scored("唯一", cost=50, total_score=0.8)], budget=5000, days=3)
        assert len(result.accepted) == 1

    def test_filter_result_structure(self):
        flt = ConstraintFilter()
        result = flt.apply([_make_scored("T")])
        assert isinstance(result, FilterResult)
        assert hasattr(result, "accepted")
        assert hasattr(result, "rejected")
        assert hasattr(result, "assumptions")
        assert hasattr(result, "relaxed")
