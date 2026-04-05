"""Tests for T-M2-000c: RankingScorer (explainable rule-based ranking).

Covers:
- Per-dimension scoring (preference, budget, rating, popularity, evidence)
- Weight normalization and custom weights
- Ranking order correctness
- top-K truncation
- QP integration via rank_from_qp
- Edge cases (empty candidates, missing fields, zero budget)
- Explainability (breakdown fields present)
"""

from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import (
    DEFAULT_WEIGHTS,
    RankingScorer,
    RankingWeights,
    ScoredCandidate,
)


def _make_candidate(
    title: str = "测试景点",
    tags: list[str] | None = None,
    score: float = 0.8,
    rating: float = 4.0,
    cost: float = 100.0,
    reviews: int = 1000,
    has_url: bool = True,
    has_address: bool = True,
) -> ProviderCandidate:
    extra = {
        "rating": rating,
        "cost_estimate": cost,
        "reviews_count": reviews,
        "address": "测试地址" if has_address else "",
    }
    if has_url:
        extra["url"] = "https://example.com"
    return ProviderCandidate(
        candidate_id=f"test-{title}",
        source="test",
        title=title,
        snippet=f"{title}的描述",
        score=score,
        tags=tags or ["景点"],
        extra=extra,
    )


# ======================== Weight Configuration ========================


class TestRankingWeights:
    def test_default_weights_sum_to_one(self):
        norm = DEFAULT_WEIGHTS.normalized()
        assert abs(sum(norm.values()) - 1.0) < 1e-9

    def test_custom_weights_normalized(self):
        w = RankingWeights(
            preference_match=2.0,
            budget_fit=1.0,
            rating=1.0,
            popularity=1.0,
            evidence_quality=0.0,
        )
        norm = w.normalized()
        assert abs(sum(norm.values()) - 1.0) < 1e-9
        assert norm["preference_match"] == 2.0 / 5.0

    def test_all_zero_weights_fallback(self):
        w = RankingWeights(
            preference_match=0, budget_fit=0,
            rating=0, popularity=0, evidence_quality=0,
        )
        norm = w.normalized()
        assert all(abs(v - 0.2) < 1e-9 for v in norm.values())


# ======================== Per-dimension Scoring ========================


class TestPreferenceScore:
    def test_full_match(self):
        c = _make_candidate(tags=["美食", "文化"])
        scorer = RankingScorer()
        sc = scorer.score_one(c, preferences=["美食", "文化"])
        assert sc.breakdown["preference_match"] == 1.0

    def test_partial_match(self):
        c = _make_candidate(tags=["美食", "购物"])
        scorer = RankingScorer()
        sc = scorer.score_one(c, preferences=["美食", "文化"])
        assert sc.breakdown["preference_match"] == 0.5

    def test_no_match(self):
        c = _make_candidate(tags=["购物"])
        scorer = RankingScorer()
        sc = scorer.score_one(c, preferences=["美食", "文化"])
        assert sc.breakdown["preference_match"] == 0.0

    def test_no_preferences_neutral(self):
        c = _make_candidate()
        scorer = RankingScorer()
        sc = scorer.score_one(c, preferences=[])
        assert sc.breakdown["preference_match"] == 0.5

    def test_snippet_match(self):
        c = _make_candidate(title="上海美食街", tags=["步行街"])
        scorer = RankingScorer()
        sc = scorer.score_one(c, preferences=["美食"])
        assert sc.breakdown["preference_match"] == 1.0


class TestBudgetScore:
    def test_exact_budget_match(self):
        c = _make_candidate(cost=200.0)
        scorer = RankingScorer()
        sc = scorer.score_one(c, daily_budget=200.0)
        assert sc.breakdown["budget_fit"] == 1.0

    def test_over_budget_penalized(self):
        c = _make_candidate(cost=400.0)
        scorer = RankingScorer()
        sc = scorer.score_one(c, daily_budget=200.0)
        assert sc.breakdown["budget_fit"] == 0.0

    def test_under_budget_partial(self):
        c = _make_candidate(cost=100.0)
        scorer = RankingScorer()
        sc = scorer.score_one(c, daily_budget=200.0)
        assert sc.breakdown["budget_fit"] == 0.5

    def test_no_budget_neutral(self):
        c = _make_candidate(cost=100.0)
        scorer = RankingScorer()
        sc = scorer.score_one(c, daily_budget=None)
        assert sc.breakdown["budget_fit"] == 0.5

    def test_no_cost_neutral(self):
        c = _make_candidate(cost=0.0)
        scorer = RankingScorer()
        sc = scorer.score_one(c, daily_budget=200.0)
        assert sc.breakdown["budget_fit"] == 0.5


class TestRatingScore:
    def test_max_rating(self):
        c = _make_candidate(rating=5.0)
        scorer = RankingScorer()
        sc = scorer.score_one(c)
        assert sc.breakdown["rating"] == 1.0

    def test_mid_rating(self):
        c = _make_candidate(rating=4.0)
        scorer = RankingScorer()
        sc = scorer.score_one(c)
        assert sc.breakdown["rating"] == 0.8

    def test_no_rating_low_default(self):
        c = _make_candidate(rating=0.0, score=0.0)
        scorer = RankingScorer()
        sc = scorer.score_one(c)
        assert sc.breakdown["rating"] == 0.3


class TestPopularityScore:
    def test_high_reviews(self):
        c = _make_candidate(reviews=50000)
        scorer = RankingScorer()
        sc = scorer.score_one(c)
        assert sc.breakdown["popularity"] >= 0.9

    def test_low_reviews(self):
        c = _make_candidate(reviews=10)
        scorer = RankingScorer()
        sc = scorer.score_one(c)
        assert sc.breakdown["popularity"] < 0.3

    def test_no_reviews(self):
        c = _make_candidate(reviews=0)
        scorer = RankingScorer()
        sc = scorer.score_one(c)
        assert sc.breakdown["popularity"] == 0.2


class TestEvidenceScore:
    def test_full_evidence(self):
        c = _make_candidate(has_url=True, has_address=True)
        c.extra["website"] = "https://example.com"
        c.extra["photos"] = ["photo1.jpg"]
        c.extra["tel"] = "123456"
        scorer = RankingScorer()
        sc = scorer.score_one(c)
        assert sc.breakdown["evidence_quality"] >= 0.8

    def test_no_evidence(self):
        c = ProviderCandidate(
            candidate_id="bare", source="test", title="空景点",
            extra={},
        )
        scorer = RankingScorer()
        sc = scorer.score_one(c)
        assert sc.breakdown["evidence_quality"] == 0.0


# ======================== Ranking Order ========================


class TestRankingOrder:
    def test_higher_preference_match_ranks_first(self):
        food = _make_candidate(title="美食街", tags=["美食", "文化"], rating=4.0)
        shopping = _make_candidate(title="购物中心", tags=["购物"], rating=4.5)

        scorer = RankingScorer(RankingWeights(preference_match=1.0, budget_fit=0, rating=0, popularity=0, evidence_quality=0))
        ranked = scorer.rank([shopping, food], preferences=["美食", "文化"])

        assert ranked[0].candidate.title == "美食街"

    def test_higher_rating_ranks_first_when_equal_pref(self):
        a = _make_candidate(title="A", tags=["文化"], rating=4.8)
        b = _make_candidate(title="B", tags=["文化"], rating=3.5)

        scorer = RankingScorer(RankingWeights(preference_match=0, budget_fit=0, rating=1.0, popularity=0, evidence_quality=0))
        ranked = scorer.rank([b, a], preferences=["文化"])

        assert ranked[0].candidate.title == "A"

    def test_budget_affects_ranking(self):
        cheap = _make_candidate(title="便宜景点", cost=50.0, rating=4.0)
        expensive = _make_candidate(title="昂贵景点", cost=500.0, rating=4.0)

        scorer = RankingScorer(RankingWeights(preference_match=0, budget_fit=1.0, rating=0, popularity=0, evidence_quality=0))
        ranked = scorer.rank([expensive, cheap], budget=400.0, days=4)

        assert ranked[0].candidate.title == "便宜景点"


# ======================== top-K and Edge Cases ========================


class TestTopK:
    def test_top_k_truncation(self):
        candidates = [_make_candidate(title=f"POI-{i}", rating=float(i)) for i in range(10)]
        scorer = RankingScorer()
        ranked = scorer.rank(candidates, top_k=5)
        assert len(ranked) == 5

    def test_top_k_larger_than_pool(self):
        candidates = [_make_candidate(title="唯一")]
        scorer = RankingScorer()
        ranked = scorer.rank(candidates, top_k=100)
        assert len(ranked) == 1

    def test_empty_candidates(self):
        scorer = RankingScorer()
        ranked = scorer.rank([], preferences=["美食"])
        assert ranked == []


# ======================== QP Integration ========================


class TestRankFromQP:
    def test_rank_from_qp_output(self):
        candidates = [
            _make_candidate(title="景点A", tags=["文化"], rating=4.5, cost=100),
            _make_candidate(title="景点B", tags=["美食"], rating=4.0, cost=200),
            _make_candidate(title="景点C", tags=["文化", "美食"], rating=3.8, cost=50),
        ]
        qp_output = {
            "constraints": {
                "preferences": ["文化", "美食"],
                "budget": 6000.0,
                "days": 4,
            }
        }
        scorer = RankingScorer()
        ranked = scorer.rank_from_qp(candidates, qp_output, top_k=10)

        assert len(ranked) == 3
        assert all(isinstance(r, ScoredCandidate) for r in ranked)
        assert ranked[0].total_score >= ranked[1].total_score >= ranked[2].total_score

    def test_rank_from_qp_missing_fields(self):
        candidates = [_make_candidate()]
        scorer = RankingScorer()
        ranked = scorer.rank_from_qp(candidates, {})
        assert len(ranked) == 1
        assert ranked[0].total_score > 0


# ======================== Explainability ========================


class TestExplainability:
    def test_breakdown_has_all_dimensions(self):
        c = _make_candidate()
        scorer = RankingScorer()
        sc = scorer.score_one(c, preferences=["美食"])

        expected_dims = {"preference_match", "budget_fit", "rating", "popularity", "evidence_quality"}
        assert set(sc.breakdown.keys()) == expected_dims

    def test_total_equals_weighted_sum(self):
        c = _make_candidate(tags=["美食"], rating=4.5, cost=100, reviews=5000)
        scorer = RankingScorer()
        sc = scorer.score_one(c, preferences=["美食"], daily_budget=200)

        w = DEFAULT_WEIGHTS.normalized()
        expected = sum(w[dim] * sc.breakdown[dim] for dim in sc.breakdown)
        assert abs(sc.total_score - round(expected, 4)) < 1e-4

    def test_scores_are_bounded(self):
        candidates = [
            _make_candidate(title=f"P{i}", rating=float(i % 5), cost=float(i * 50))
            for i in range(20)
        ]
        scorer = RankingScorer()
        ranked = scorer.rank(candidates, preferences=["文化"], budget=5000, days=3)

        for sc in ranked:
            assert 0.0 <= sc.total_score <= 1.0
            for dim, val in sc.breakdown.items():
                assert 0.0 <= val <= 1.0, f"{dim} = {val} out of bounds"
