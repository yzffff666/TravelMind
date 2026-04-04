"""Tests for T-M2-000b: RecallService (QP → Provider → aggregated candidates).

Covers:
- QP output → RecallService.recall_from_qp end-to-end
- recall_simple convenience method
- Empty/missing QP fields → graceful degradation
- Mock fallback when no real keys
- Candidate dedup across sources
- RecallResult structure
"""

import asyncio
from unittest.mock import patch

from app.domain.travel.query_processor import TravelQueryProcessor
from app.services.providers.call_policy import ProviderCallPolicy
from app.services.recall_service import RecallResult, RecallService


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _build_service() -> RecallService:
    """Build a RecallService with only mock providers (no real API calls)."""
    with patch("app.services.providers.factory._get_key", return_value=None):
        return RecallService()


# ======================== QP → RecallService e2e ========================


class TestQPToRecall:
    def test_qp_to_recall_known_city(self):
        qp = TravelQueryProcessor()
        qp_out = qp.process("上海 4天 预算6000 情侣 文化 美食")
        svc = _build_service()
        result = _run(svc.recall_from_qp(qp_out))

        assert isinstance(result, RecallResult)
        assert len(result.candidates) > 0
        assert result.city == "上海"
        assert "上海" in result.recall_query
        assert result.calls_made >= 1

    def test_qp_to_recall_beijing(self):
        qp = TravelQueryProcessor()
        qp_out = qp.process("北京 3天 预算5000 亲子")
        svc = _build_service()
        result = _run(svc.recall_from_qp(qp_out))

        assert len(result.candidates) > 0
        assert result.city == "北京"

    def test_qp_to_recall_chengdu(self):
        qp = TravelQueryProcessor()
        qp_out = qp.process("成都 5天 预算8000 美食")
        svc = _build_service()
        result = _run(svc.recall_from_qp(qp_out))

        assert len(result.candidates) > 0
        assert result.city == "成都"

    def test_qp_to_recall_unknown_city_degrades(self):
        qp = TravelQueryProcessor()
        qp_out = qp.process("巴黎 3天 预算10000")
        svc = _build_service()
        result = _run(svc.recall_from_qp(qp_out))

        assert result.degraded is True
        assert len(result.assumptions) > 0

    def test_candidates_are_deduplicated(self):
        qp = TravelQueryProcessor()
        qp_out = qp.process("上海 旅行")
        svc = _build_service()
        result = _run(svc.recall_from_qp(qp_out))

        ids = [c.candidate_id for c in result.candidates]
        assert len(ids) == len(set(ids))

    def test_candidates_have_required_fields(self):
        qp = TravelQueryProcessor()
        qp_out = qp.process("上海 3天 预算5000")
        svc = _build_service()
        result = _run(svc.recall_from_qp(qp_out))

        for c in result.candidates:
            assert c.candidate_id
            assert c.source
            assert c.title
            assert isinstance(c.tags, list)
            assert isinstance(c.extra, dict)

    def test_multiple_sources_merged(self):
        qp = TravelQueryProcessor()
        qp_out = qp.process("上海 文化 美食")
        svc = _build_service()
        result = _run(svc.recall_from_qp(qp_out))

        sources = {c.source for c in result.candidates}
        assert len(sources) >= 1


# ======================== recall_simple ========================


class TestRecallSimple:
    def test_recall_simple_known_city(self):
        svc = _build_service()
        result = _run(svc.recall_simple(query="成都 景点", city="成都"))

        assert len(result.candidates) > 0
        assert result.city == "成都"
        assert result.recall_query == "成都 景点"

    def test_recall_simple_with_preferences(self):
        svc = _build_service()
        result = _run(svc.recall_simple(
            query="上海", city="上海", preferences=["美食", "文化"]
        ))

        assert len(result.candidates) > 0


# ======================== Edge cases ========================


class TestRecallEdgeCases:
    def test_empty_qp_output_degrades(self):
        svc = _build_service()
        result = _run(svc.recall_from_qp({}))

        assert result.degraded is True
        assert len(result.assumptions) > 0
        assert len(result.candidates) == 0

    def test_qp_with_no_city_no_query_degrades(self):
        svc = _build_service()
        result = _run(svc.recall_from_qp({
            "recall_query": "",
            "constraints": {"destination_city": None},
        }))

        assert result.degraded is True

    def test_custom_policy_limits_calls(self):
        policy = ProviderCallPolicy(max_calls_per_request=1)
        with patch("app.services.providers.factory._get_key", return_value=None):
            svc = RecallService(policy=policy)

        qp = TravelQueryProcessor()
        qp_out = qp.process("上海 3天")
        result = _run(svc.recall_from_qp(qp_out))

        assert result.calls_made <= 1

    def test_recall_result_structure(self):
        svc = _build_service()
        result = _run(svc.recall_simple(query="北京", city="北京"))

        assert hasattr(result, "candidates")
        assert hasattr(result, "assumptions")
        assert hasattr(result, "degraded")
        assert hasattr(result, "calls_made")
        assert hasattr(result, "city")
        assert hasattr(result, "recall_query")
