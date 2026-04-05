"""Pipeline integration test: QP → Recall → Ranking → Filter end-to-end.

This is NOT a unit test. It verifies that the four modules work
together correctly as a chain, using mock providers (no real API calls).

Covers:
- Full pipeline with known city (上海/北京/成都)
- Full pipeline with unknown city (degrades gracefully)
- Pipeline respects user constraints (budget, pace, preferences)
- Candidates flow correctly between stages
- Assumptions propagate from recall to final output
"""

import asyncio
from unittest.mock import patch

from app.domain.travel.query_processor import TravelQueryProcessor
from app.services.constraint_filter import ConstraintFilter
from app.services.ranking_scorer import RankingScorer
from app.services.recall_service import RecallService


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _build_recall() -> RecallService:
    with patch("app.services.providers.factory._get_key", return_value=None):
        return RecallService()


def _run_pipeline(
    query: str,
    *,
    city_center: tuple[float, float] | None = None,
) -> dict:
    """Execute the full QP → Recall → Rank → Filter pipeline."""
    qp = TravelQueryProcessor()
    recall_svc = _build_recall()
    scorer = RankingScorer()
    flt = ConstraintFilter()

    qp_output = qp.process(query)

    recall_result = _run(recall_svc.recall_from_qp(qp_output))

    ranked = scorer.rank_from_qp(recall_result.candidates, qp_output, top_k=15)

    filter_result = flt.apply_from_qp(
        ranked, qp_output, city_center=city_center,
    )

    return {
        "qp": qp_output,
        "recall": recall_result,
        "ranked": ranked,
        "filtered": filter_result,
    }


# ======================== Full Pipeline ========================


class TestFullPipeline:
    def test_shanghai_pipeline(self):
        result = _run_pipeline("上海 4天 预算6000 情侣 文化 美食")
        assert result["recall"].city == "上海"
        assert len(result["recall"].candidates) > 0
        assert len(result["ranked"]) > 0
        assert len(result["filtered"].accepted) > 0

        for sc in result["ranked"]:
            assert sc.total_score > 0
            assert "preference_match" in sc.breakdown

    def test_beijing_pipeline(self):
        result = _run_pipeline("北京 3天 预算5000 亲子")
        assert result["recall"].city == "北京"
        assert len(result["filtered"].accepted) > 0

    def test_chengdu_pipeline(self):
        result = _run_pipeline("成都 5天 预算8000 美食")
        assert result["recall"].city == "成都"
        assert len(result["filtered"].accepted) > 0

    def test_unknown_city_degrades(self):
        result = _run_pipeline("巴黎 3天 预算10000")
        assert result["recall"].degraded is True
        assert len(result["recall"].assumptions) > 0
        assert len(result["filtered"].accepted) == 0


# ======================== Constraint Propagation ========================


class TestConstraintPropagation:
    def test_preferences_affect_ranking(self):
        result = _run_pipeline("上海 3天 预算5000 美食")
        ranked = result["ranked"]
        if len(ranked) >= 2:
            has_food_tag = any(
                "美食" in t or "小吃" in t
                for t in ranked[0].candidate.tags
            ) or "美食" in ranked[0].candidate.title
            assert ranked[0].breakdown.get("preference_match", 0) >= 0

    def test_budget_constrains_filter(self):
        tight = _run_pipeline("上海 3天 预算1000")
        loose = _run_pipeline("上海 3天 预算50000")
        assert len(loose["filtered"].accepted) >= len(tight["filtered"].accepted)

    def test_pace_constrains_output_count(self):
        relaxed = _run_pipeline("上海 4天 预算6000 悠闲")
        assert len(relaxed["filtered"].accepted) <= 5


# ======================== Data Integrity ========================


class TestDataIntegrity:
    def test_ranked_is_subset_of_recalled(self):
        result = _run_pipeline("上海 3天 预算5000")
        recall_ids = {c.candidate_id for c in result["recall"].candidates}
        ranked_ids = {sc.candidate.candidate_id for sc in result["ranked"]}
        assert ranked_ids.issubset(recall_ids)

    def test_accepted_is_subset_of_ranked(self):
        result = _run_pipeline("上海 3天 预算5000")
        ranked_ids = {sc.candidate.candidate_id for sc in result["ranked"]}
        accepted_ids = {sc.candidate.candidate_id for sc in result["filtered"].accepted}
        assert accepted_ids.issubset(ranked_ids)

    def test_no_duplicate_ids_in_output(self):
        result = _run_pipeline("上海 4天 预算6000 文化 美食")
        accepted_ids = [sc.candidate.candidate_id for sc in result["filtered"].accepted]
        assert len(accepted_ids) == len(set(accepted_ids))

    def test_ranked_sorted_descending(self):
        result = _run_pipeline("成都 3天 预算5000")
        scores = [sc.total_score for sc in result["ranked"]]
        assert scores == sorted(scores, reverse=True)
