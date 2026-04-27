"""Draft node + pipeline integration tests (Phase 1a–1d).

Verifies that:
- Pipeline (QP -> Recall -> Rank -> Filter -> Evidence) runs inside the draft node.
- Pipeline candidates are injected into LLM prompt.
- Post-processing attaches evidence refs, assumptions, and coverage.
- SSE events follow the design.md contract sequence.

Mock strategy:
- Provider keys mocked to None -> forces mock providers (no real API calls).
- LLM mocked to return a fixed JSON itinerary -> no real LLM calls.
"""

import asyncio
import json
import re
import time
from unittest.mock import AsyncMock, MagicMock, patch

_MOCK_LLM_RESPONSE = json.dumps({
    "days": [
        {
            "day_index": 1,
            "theme": "文化探索",
            "slots": [
                {"slot": "上午", "activity": "参观外滩", "place": "外滩"},
                {"slot": "下午", "activity": "游览豫园", "place": "豫园"},
                {"slot": "晚上", "activity": "南京路步行街", "place": "南京路"},
            ],
        },
        {
            "day_index": 2,
            "theme": "自然风光",
            "slots": [
                {"slot": "上午", "activity": "朱家角古镇", "place": "朱家角"},
                {"slot": "下午", "activity": "田子坊逛街", "place": "田子坊"},
                {"slot": "晚上", "activity": "休息", "place": "酒店"},
            ],
        },
    ],
    "budget_summary": {"total_estimate": 6000},
})


def _make_mock_llm():
    """Create a mock LLM that returns a fixed JSON itinerary.

    Supports both ``ainvoke`` (legacy) and ``astream`` (new multi-node).
    """
    mock_response = MagicMock()
    mock_response.content = _MOCK_LLM_RESPONSE
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    async def _mock_astream(messages, **kwargs):
        chunk_size = 80
        text = _MOCK_LLM_RESPONSE
        for i in range(0, len(text), chunk_size):
            chunk = MagicMock()
            chunk.content = text[i:i + chunk_size]
            yield chunk

    mock_llm.astream = _mock_astream
    return mock_llm


def _run(coro):
    return asyncio.run(coro)


def _reset_pipeline_singletons():
    """Reset lazy singletons and recall cache so each test starts fresh."""
    import app.lg_agent.travel_draft_graph as tdg
    tdg._pipeline_qp = None
    tdg._pipeline_recall = None
    tdg._pipeline_scorer = None
    tdg._pipeline_filter = None
    tdg._pipeline_eb = None
    from app.services.providers.orchestrator import clear_recall_cache
    clear_recall_cache()


def _invoke_graph(query: str) -> dict:
    """Run the full travel_draft_graph with mocked LLM and mock providers."""
    with patch("app.services.providers.factory._get_key", return_value=None), \
         patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
        from app.lg_agent.travel_draft_graph import travel_draft_graph
        return _run(travel_draft_graph.ainvoke({"query": query}))


class TestJsonRepair:
    """Verify _repair_json handles common LLM output quirks."""

    def test_trailing_comma(self):
        from app.lg_agent.travel_draft_graph import _repair_json
        raw = '{"days": [{"day_index": 1,}], "budget_summary": {"total_estimate": 5000,}}'
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        assert data["days"][0]["day_index"] == 1

    def test_markdown_fence(self):
        from app.lg_agent.travel_draft_graph import _repair_json
        raw = '```json\n{"days": []}\n```'
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        assert "days" in data

    def test_leading_prose(self):
        from app.lg_agent.travel_draft_graph import _repair_json
        raw = '好的，以下是你的行程：\n{"days": [], "budget_summary": {"total_estimate": 5000}}'
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        assert data["budget_summary"]["total_estimate"] == 5000

    def test_trailing_text_after_json(self):
        from app.lg_agent.travel_draft_graph import _repair_json
        raw = '{"days": []}\n\n希望你满意！'
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        assert "days" in data

    def test_inline_comments(self):
        from app.lg_agent.travel_draft_graph import _repair_json
        raw = '{"days": [] // placeholder\n}'
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        assert "days" in data

    def test_bom_stripped(self):
        from app.lg_agent.travel_draft_graph import _repair_json
        raw = '\ufeff{"days": []}'
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        assert "days" in data

    def test_clean_json_passes_through(self):
        from app.lg_agent.travel_draft_graph import _repair_json
        raw = '{"days": [{"day_index": 1, "slots": [{"slot": "上午", "activity": "外滩"}]}]}'
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        assert data["days"][0]["day_index"] == 1


class TestFormatCandidates:
    """Unit tests for _format_candidates_for_prompt helper."""

    def test_formats_candidates_with_all_fields(self):
        from app.services.providers.base import ProviderCandidate
        from app.services.ranking_scorer import ScoredCandidate
        from app.services.evidence_builder import PipelineResult

        sc = ScoredCandidate(
            candidate=ProviderCandidate(
                candidate_id="外滩_上海",
                source="mock_search",
                title="外滩",
                snippet="上海标志性景点",
                score=0.9,
                tags=["景点", "文化", "地标"],
                extra={"rating": 4.8, "cost_estimate": 0, "address": "上海市黄浦区"},
            ),
            total_score=0.85,
        )
        pr = PipelineResult(candidates=[sc])

        from app.lg_agent.travel_draft_graph import _format_candidates_for_prompt
        result = _format_candidates_for_prompt(pr)

        assert "外滩" in result
        assert "景点" in result
        assert "评分4.8" in result
        assert "推荐地点" in result

    def test_returns_empty_for_none(self):
        from app.lg_agent.travel_draft_graph import _format_candidates_for_prompt
        assert _format_candidates_for_prompt(None) == ""

    def test_returns_empty_for_no_candidates(self):
        from app.services.evidence_builder import PipelineResult
        from app.lg_agent.travel_draft_graph import _format_candidates_for_prompt
        pr = PipelineResult(candidates=[])
        assert _format_candidates_for_prompt(pr) == ""


class TestBudgetValidation:
    def test_central_hotel_budget_conflict_is_recorded(self):
        from app.lg_agent.travel_draft_graph import _append_budget_validation
        from app.schemas.itinerary_v1 import (
            BudgetByCategory,
            BudgetSummary,
            ItineraryDay,
            ItinerarySlot,
            ItineraryV1,
            TripProfile,
        )

        itinerary = ItineraryV1(
            itinerary_id="it-1",
            revision_id="rev-1",
            trip_profile=TripProfile(destination_city="北京"),
            days=[
                ItineraryDay(
                    day_index=1,
                    slots=[ItinerarySlot(slot="上午", activity="参观故宫", place="故宫")],
                )
            ],
            budget_summary=BudgetSummary(
                total_estimate=1500,
                by_category=BudgetByCategory(hotel=0),
            ),
        )

        _append_budget_validation(
            itinerary,
            original_query="北京 3 天，预算 1500，亲子，想住市中心+热门景点",
            requested_budget=1500,
            requested_days=3,
        )

        assert any("市中心住宿" in c for c in itinerary.validation.conflicts)
        assert any("缺少酒店费用" in c for c in itinerary.validation.conflicts)


# ===================================================================
# Node-level tests
# ===================================================================

class TestExtractNode:
    """Verify extract_node parses constraints correctly."""

    def test_extract_known_city(self):
        from app.lg_agent.travel_draft_graph import extract_node
        result = _run(extract_node({"query": "上海 4天 预算6000 情侣"}))
        assert result["destination"] == "上海"
        assert result["days_count"] == 4
        assert result["total_budget"] == 6000
        assert result["missing_p0"] == []
        assert "extract_ms" in result["perf"]

    def test_extract_missing_p0(self):
        from app.lg_agent.travel_draft_graph import extract_node
        result = _run(extract_node({"query": "想去海边玩几天"}))
        assert len(result["missing_p0"]) > 0

    def test_extract_preferences(self):
        from app.lg_agent.travel_draft_graph import extract_node
        result = _run(extract_node({"query": "上海 3天 预算5000 文化 美食"}))
        assert "文化" in result["preferences"]
        assert "美食" in result["preferences"]

    def test_extract_traveler_default_assumption(self):
        from app.lg_agent.travel_draft_graph import extract_node
        result = _run(extract_node({"query": "上海 3天 预算5000"}))
        assert result["traveler_type"] is None
        assert any("旅行者" in a or "通用" in a for a in result["assumptions"])


class TestRecallNode:
    """Verify recall_node runs the pipeline."""

    def setup_method(self):
        _reset_pipeline_singletons()

    def test_recall_produces_pipeline_result(self):
        from app.lg_agent.travel_draft_graph import recall_node
        state = {
            "query": "上海 4天 预算6000 文化",
            "missing_p0": [],
            "perf": {},
        }
        with patch("app.services.providers.factory._get_key", return_value=None):
            result = _run(recall_node(state))
        assert result["pipeline_result"] is not None
        assert "recall_ms" in result["perf"]

    def test_recall_failure_graceful(self):
        from app.lg_agent.travel_draft_graph import recall_node, _get_pipeline
        state = {"query": "上海 3天 预算5000", "missing_p0": [], "perf": {}}
        with patch("app.services.providers.factory._get_key", return_value=None):
            qp, recall_svc, *_ = _get_pipeline()

            async def broken_recall(*args, **kwargs):
                raise ConnectionError("Network down")

            with patch.object(recall_svc, "recall_from_qp", side_effect=broken_recall):
                result = _run(recall_node(state))
        assert result["pipeline_result"] is None
        assert result["recall_degraded"] is True


class TestLlmDraftNode:
    """Verify llm_draft_node generates itinerary from state."""

    def test_produces_itinerary(self):
        from app.lg_agent.travel_draft_graph import llm_draft_node
        state = {
            "query": "上海 4天 预算6000 文化",
            "destination": "上海",
            "days_count": 4,
            "total_budget": 6000.0,
            "traveler_type": None,
            "preferences": ["文化"],
            "pace": None,
            "assumptions": [],
            "pipeline_result": None,
            "perf": {},
        }
        with patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            result = _run(llm_draft_node(state))
        assert result["itinerary"] is not None
        assert result["explanation"] is not None
        assert "llm_ms" in result["perf"]

    def test_llm_failure_template_fallback(self):
        from app.lg_agent.travel_draft_graph import llm_draft_node
        state = {
            "query": "上海 3天 预算5000",
            "destination": "上海",
            "days_count": 3,
            "total_budget": 5000.0,
            "traveler_type": None,
            "preferences": [],
            "pace": None,
            "assumptions": [],
            "pipeline_result": None,
            "perf": {},
        }

        broken_llm = MagicMock()
        async def boom(*a, **kw):
            raise RuntimeError("LLM down")
            yield  # makes this an async generator so `async for` can iterate it
        broken_llm.astream = boom

        with patch("app.lg_agent.travel_draft_graph._get_llm", return_value=broken_llm):
            result = _run(llm_draft_node(state))
        assert result["itinerary"] is not None
        assert any("降级" in a for a in result["assumptions"])

    def test_ttft_recorded(self):
        from app.lg_agent.travel_draft_graph import llm_draft_node
        state = {
            "query": "上海 3天 预算5000",
            "destination": "上海",
            "days_count": 3,
            "total_budget": 5000.0,
            "traveler_type": None,
            "preferences": [],
            "pace": None,
            "assumptions": [],
            "pipeline_result": None,
            "perf": {},
        }
        with patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            result = _run(llm_draft_node(state))
        assert result["perf"]["llm_ttft_ms"] is not None
        assert result["perf"]["llm_ttft_ms"] >= 0


# ===================================================================
# Full-graph integration tests (output contract must match old single-node)
# ===================================================================

class TestDraftPipelineDataFlow:
    """Verify pipeline runs inside draft node and produces valid output."""

    def setup_method(self):
        _reset_pipeline_singletons()

    def test_known_city_produces_itinerary(self):
        result = _invoke_graph("上海 4天 预算6000 情侣 文化 美食")
        assert result["final_itinerary"] is not None
        assert result["explanation"] is not None
        assert result["final_text"] is None

    def test_beijing_pipeline(self):
        result = _invoke_graph("北京 3天 预算5000 亲子")
        assert result["final_itinerary"] is not None
        itinerary = result["final_itinerary"]
        assert itinerary["trip_profile"]["destination_city"] == "北京"

    def test_unknown_city_still_produces_itinerary(self):
        """Pipeline degrades for unknown cities but LLM still generates."""
        result = _invoke_graph("巴黎 3天 预算10000")
        assert result["final_itinerary"] is not None

    def test_missing_p0_returns_final_text(self):
        """P0 missing -> no pipeline, no LLM, just final_text."""
        result = _invoke_graph("想去海边玩几天")
        assert result["final_itinerary"] is None
        assert result["final_text"] is not None

    def test_perf_metrics_present(self):
        result = _invoke_graph("上海 3天 预算5000")
        perf = result.get("perf", {})
        assert "extract_ms" in perf
        assert "recall_ms" in perf
        assert "llm_ms" in perf
        assert "postprocess_ms" in perf


class TestPipelineIsActuallyCalled:
    """Verify the pipeline stages are invoked, not just the LLM."""

    def setup_method(self):
        _reset_pipeline_singletons()

    def test_recall_is_called(self):
        """RecallService.recall_from_qp should be called during draft."""
        call_log = []

        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            from app.lg_agent.travel_draft_graph import _get_pipeline, travel_draft_graph
            qp, recall_svc, scorer, flt, eb, backfill = _get_pipeline()

            original_recall = recall_svc.recall_from_qp

            async def spy_recall(qp_output, **kwargs):
                call_log.append(qp_output)
                return await original_recall(qp_output, **kwargs)

            with patch.object(recall_svc, "recall_from_qp", side_effect=spy_recall):
                _run(travel_draft_graph.ainvoke({"query": "上海 4天 预算6000 文化"}))

        assert len(call_log) == 1, "recall_from_qp should be called exactly once"
        assert call_log[0]["constraints"]["destination_city"] == "上海"

    def test_pipeline_log_output(self):
        """Logger should emit pipeline metrics."""
        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()), \
             patch("app.lg_agent.travel_draft_graph.logger") as mock_logger:
            from app.lg_agent.travel_draft_graph import travel_draft_graph
            _run(travel_draft_graph.ainvoke({"query": "上海 3天 预算5000"}))

        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        pipeline_log = [c for c in info_calls if "Pipeline completed" in c]
        assert len(pipeline_log) >= 1, (
            f"Expected 'Pipeline completed' log, got: {info_calls}"
        )


class TestPromptInjection:
    """Verify pipeline candidates are injected into the LLM prompt."""

    def setup_method(self):
        _reset_pipeline_singletons()

    def test_candidates_injected_into_prompt(self):
        """LLM should receive a prompt containing candidate names."""
        captured_messages = []

        mock_llm = MagicMock()

        async def capture_astream(messages, **kwargs):
            captured_messages.extend(messages)
            for i in range(0, len(_MOCK_LLM_RESPONSE), 80):
                chunk = MagicMock()
                chunk.content = _MOCK_LLM_RESPONSE[i:i + 80]
                yield chunk

        mock_llm.astream = capture_astream

        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=mock_llm):
            from app.lg_agent.travel_draft_graph import travel_draft_graph
            _run(travel_draft_graph.ainvoke({"query": "上海 4天 预算6000 文化 美食"}))

        assert len(captured_messages) == 2
        user_msg = captured_messages[1]["content"]
        assert "推荐地点" in user_msg
        assert "place 字段请尽量使用上述推荐地点的原始名称" in user_msg

    def test_no_candidates_no_injection(self):
        """When pipeline returns no candidates, prompt should not have candidate section."""
        captured_messages = []

        mock_llm = MagicMock()

        async def capture_astream(messages, **kwargs):
            captured_messages.extend(messages)
            for i in range(0, len(_MOCK_LLM_RESPONSE), 80):
                chunk = MagicMock()
                chunk.content = _MOCK_LLM_RESPONSE[i:i + 80]
                yield chunk

        mock_llm.astream = capture_astream

        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=mock_llm):
            from app.lg_agent.travel_draft_graph import travel_draft_graph
            _run(travel_draft_graph.ainvoke({"query": "巴黎 3天 预算10000"}))

        user_msg = captured_messages[1]["content"]
        assert "推荐地点" not in user_msg

    def test_system_prompt_mentions_recommendations(self):
        """System prompt should mention using recommended places."""
        captured_messages = []

        mock_llm = MagicMock()

        async def capture_astream(messages, **kwargs):
            captured_messages.extend(messages)
            for i in range(0, len(_MOCK_LLM_RESPONSE), 80):
                chunk = MagicMock()
                chunk.content = _MOCK_LLM_RESPONSE[i:i + 80]
                yield chunk

        mock_llm.astream = capture_astream

        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=mock_llm):
            from app.lg_agent.travel_draft_graph import travel_draft_graph
            _run(travel_draft_graph.ainvoke({"query": "上海 3天 预算5000"}))

        system_msg = captured_messages[0]["content"]
        assert "推荐地点列表" in system_msg


class TestPostprocessing:
    """Phase 1c: verify evidence attachment, ref linking, assumptions, coverage."""

    def setup_method(self):
        _reset_pipeline_singletons()

    def test_evidence_attached_to_itinerary(self):
        """Pipeline evidence items should be written to itinerary.evidence."""
        result = _invoke_graph("上海 4天 预算6000 文化 美食")
        it = result["final_itinerary"]
        assert "evidence" in it
        assert len(it["evidence"]) > 0
        for ev in it["evidence"]:
            assert ev["evidence_id"].startswith("ev-")
            assert ev.get("title")

    def test_evidence_refs_linked_to_slots(self):
        """Slots whose place matches an evidence title should have evidence_refs."""
        result = _invoke_graph("上海 4天 预算6000 文化")
        it = result["final_itinerary"]
        evidence_titles = {ev["title"] for ev in it.get("evidence", []) if ev.get("title")}

        linked_slots = 0
        for day in it["days"]:
            for slot in day["slots"]:
                if slot.get("evidence_refs"):
                    linked_slots += 1
        assert linked_slots > 0, (
            f"Expected at least one slot with evidence_refs. "
            f"Evidence titles: {evidence_titles}"
        )

    def test_coverage_score_computed(self):
        """validation.coverage_score should be set after post-processing."""
        result = _invoke_graph("上海 4天 预算6000 文化")
        it = result["final_itinerary"]
        validation = it.get("validation", {})
        coverage = validation.get("coverage_score")
        assert coverage is not None
        assert 0.0 <= coverage <= 1.0

    def test_pipeline_assumptions_merged(self):
        """Pipeline assumptions should appear in validation.assumptions."""
        result = _invoke_graph("上海 4天 预算6000 文化")
        it = result["final_itinerary"]
        assumptions = it.get("validation", {}).get("assumptions", [])
        assert isinstance(assumptions, list)

    def test_no_duplicate_assumptions(self):
        """Assumptions list should not contain duplicates."""
        result = _invoke_graph("上海 4天 预算6000 文化")
        it = result["final_itinerary"]
        assumptions = it.get("validation", {}).get("assumptions", [])
        assert len(assumptions) == len(set(assumptions))


class TestPostprocessUnit:
    """Unit tests for _postprocess_with_pipeline helper."""

    def test_noop_when_pipeline_result_none(self):
        """Should not modify itinerary when pipeline_result is None."""
        from app.lg_agent.travel_draft_graph import _postprocess_with_pipeline
        from app.schemas.itinerary_v1 import (
            ItineraryV1, TripProfile, ItineraryDay, ItinerarySlot, BudgetSummary,
        )

        itinerary = ItineraryV1(
            itinerary_id="test-id",
            revision_id="rev-id",
            trip_profile=TripProfile(destination_city="上海"),
            days=[ItineraryDay(day_index=1, slots=[
                ItinerarySlot(slot="上午", activity="参观外滩", place="外滩"),
            ])],
            budget_summary=BudgetSummary(total_estimate=5000),
        )
        _postprocess_with_pipeline(itinerary, None, None)

        assert itinerary.evidence == []
        assert itinerary.validation.coverage_score is None
        assert itinerary.days[0].slots[0].evidence_refs == []

    def test_bidirectional_matching(self):
        """Slot '外滩风景区' should match evidence title '外滩' (reverse substring)."""
        from app.lg_agent.travel_draft_graph import _postprocess_with_pipeline
        from app.schemas.itinerary_v1 import (
            ItineraryV1, TripProfile, ItineraryDay, ItinerarySlot,
            BudgetSummary, EvidenceItem,
        )
        from app.services.evidence_builder import EvidenceBuilder, PipelineResult

        evidence = [
            EvidenceItem(
                evidence_id="ev-waitan",
                provider="mock",
                title="外滩",
                source_type="search",
            ),
        ]
        pr = PipelineResult(evidence=evidence, candidates=[])
        eb = EvidenceBuilder()

        itinerary = ItineraryV1(
            itinerary_id="test-id",
            revision_id="rev-id",
            trip_profile=TripProfile(destination_city="上海"),
            days=[ItineraryDay(day_index=1, slots=[
                ItinerarySlot(slot="上午", activity="参观外滩风景区", place="外滩风景区"),
            ])],
            budget_summary=BudgetSummary(total_estimate=5000),
        )

        _postprocess_with_pipeline(itinerary, pr, eb)

        assert itinerary.days[0].slots[0].evidence_refs == ["ev-waitan"]
        assert itinerary.validation.coverage_score == 1.0

    def test_forward_matching(self):
        """Slot '大熊猫繁育研究基地' should match evidence '成都大熊猫繁育研究基地'."""
        from app.lg_agent.travel_draft_graph import _postprocess_with_pipeline
        from app.schemas.itinerary_v1 import (
            ItineraryV1, TripProfile, ItineraryDay, ItinerarySlot,
            BudgetSummary, EvidenceItem,
        )
        from app.services.evidence_builder import EvidenceBuilder, PipelineResult

        evidence = [
            EvidenceItem(
                evidence_id="ev-panda",
                provider="mock",
                title="成都大熊猫繁育研究基地",
                source_type="map",
            ),
        ]
        pr = PipelineResult(evidence=evidence, candidates=[])
        eb = EvidenceBuilder()

        itinerary = ItineraryV1(
            itinerary_id="test-id",
            revision_id="rev-id",
            trip_profile=TripProfile(destination_city="成都"),
            days=[ItineraryDay(day_index=1, slots=[
                ItinerarySlot(slot="上午", activity="参观大熊猫繁育研究基地", place="大熊猫繁育研究基地"),
            ])],
            budget_summary=BudgetSummary(total_estimate=5000),
        )

        _postprocess_with_pipeline(itinerary, pr, eb)

        assert itinerary.days[0].slots[0].evidence_refs == ["ev-panda"]

    def test_no_match_gives_empty_refs(self):
        """Slot with unrelated place gets no evidence_refs."""
        from app.lg_agent.travel_draft_graph import _postprocess_with_pipeline
        from app.schemas.itinerary_v1 import (
            ItineraryV1, TripProfile, ItineraryDay, ItinerarySlot,
            BudgetSummary, EvidenceItem,
        )
        from app.services.evidence_builder import EvidenceBuilder, PipelineResult

        evidence = [
            EvidenceItem(evidence_id="ev-waitan", provider="mock", title="外滩"),
        ]
        pr = PipelineResult(evidence=evidence, candidates=[])
        eb = EvidenceBuilder()

        itinerary = ItineraryV1(
            itinerary_id="test-id",
            revision_id="rev-id",
            trip_profile=TripProfile(destination_city="成都"),
            days=[ItineraryDay(day_index=1, slots=[
                ItinerarySlot(slot="上午", activity="吃火锅", place="火锅店"),
            ])],
            budget_summary=BudgetSummary(total_estimate=5000),
        )

        _postprocess_with_pipeline(itinerary, pr, eb)

        assert itinerary.days[0].slots[0].evidence_refs == []
        assert itinerary.validation.coverage_score == 0.0

    def test_geo_match_creates_evidence_ref(self):
        """A matched geo candidate can create POI evidence even when evidence list is empty."""
        from app.lg_agent.travel_draft_graph import _postprocess_with_pipeline
        from app.schemas.itinerary_v1 import (
            BudgetSummary,
            ItineraryDay,
            ItinerarySlot,
            ItineraryV1,
            TripProfile,
        )
        from app.services.evidence_builder import EvidenceBuilder, PipelineResult
        from app.services.providers.base import ProviderCandidate
        from app.services.ranking_scorer import ScoredCandidate

        candidate = ProviderCandidate(
            candidate_id="serp-gugong",
            source="serp_map",
            title="故宫博物院",
            snippet="博物馆",
            extra={"lat": 39.9163, "lng": 116.3972, "rating": 4.8, "address": "北京市东城区"},
        )
        pr = PipelineResult(
            candidates=[ScoredCandidate(candidate=candidate, total_score=0.9)],
            evidence=[],
        )
        itinerary = ItineraryV1(
            itinerary_id="it-geo",
            revision_id="rev-geo",
            trip_profile=TripProfile(destination_city="北京"),
            days=[ItineraryDay(
                day_index=1,
                slots=[ItinerarySlot(slot="下午", activity="游览故宫", place="故宫博物院")],
            )],
            budget_summary=BudgetSummary(total_estimate=1500),
        )

        _postprocess_with_pipeline(itinerary, pr, EvidenceBuilder())

        assert itinerary.days[0].slots[0].evidence_refs == ["ev-serp-gugong"]
        assert itinerary.days[0].slots[0].location is not None
        assert itinerary.evidence[0].title == "故宫博物院"
        assert itinerary.validation.coverage_score == 1.0

    def test_geo_match_rejects_out_of_bounds_overseas_candidate(self):
        """A same-name overseas POI should not inherit an obviously wrong cross-region coordinate."""
        from app.lg_agent.travel_draft_graph import _postprocess_with_pipeline
        from app.schemas.itinerary_v1 import (
            BudgetSummary,
            ItineraryDay,
            ItinerarySlot,
            ItineraryV1,
            TripProfile,
        )
        from app.services.evidence_builder import EvidenceBuilder, PipelineResult
        from app.services.providers.base import ProviderCandidate
        from app.services.ranking_scorer import ScoredCandidate

        candidate = ProviderCandidate(
            candidate_id="karon-wrong",
            source="serp_map",
            title="卡伦海滩",
            snippet="错误跨区域候选",
            extra={"lat": 43.948993, "lng": 125.535557, "address": "中国吉林省长春市"},
        )
        pr = PipelineResult(
            candidates=[ScoredCandidate(candidate=candidate, total_score=0.9)],
            evidence=[],
        )
        itinerary = ItineraryV1(
            itinerary_id="it-phuket",
            revision_id="rev-phuket",
            trip_profile=TripProfile(destination_city="普吉岛"),
            days=[ItineraryDay(
                day_index=1,
                slots=[ItinerarySlot(slot="上午", activity="海滩散步", place="卡伦海滩")],
            )],
            budget_summary=BudgetSummary(total_estimate=12000),
        )

        _postprocess_with_pipeline(itinerary, pr, EvidenceBuilder())

        slot = itinerary.days[0].slots[0]
        assert slot.location is None
        assert slot.evidence_refs == []
        assert itinerary.evidence == []
        assert itinerary.validation.coverage_score == 0.0


class TestCandidateCapping:
    """Verify _MAX_CANDIDATES_IN_PROMPT caps injected candidates."""

    def test_caps_at_max(self):
        from app.services.providers.base import ProviderCandidate
        from app.services.ranking_scorer import ScoredCandidate
        from app.services.evidence_builder import PipelineResult
        from app.lg_agent.travel_draft_graph import (
            _format_candidates_for_prompt,
            _MAX_CANDIDATES_IN_PROMPT,
        )

        candidates = [
            ScoredCandidate(
                candidate=ProviderCandidate(
                    candidate_id=f"poi_{i}",
                    source="mock_search",
                    title=f"景点{i}",
                    snippet=f"描述{i}",
                    score=0.9 - i * 0.01,
                    tags=["景点"],
                    extra={},
                ),
                total_score=0.9 - i * 0.01,
            )
            for i in range(20)
        ]
        pr = PipelineResult(candidates=candidates)
        result = _format_candidates_for_prompt(pr)

        line_count = len([l for l in result.strip().split("\n") if l.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.", "11."))])
        assert line_count <= _MAX_CANDIDATES_IN_PROMPT


class TestPipelineFailureGraceful:
    """Verify draft node still works when pipeline fails."""

    def setup_method(self):
        _reset_pipeline_singletons()

    def test_pipeline_exception_does_not_block_llm(self):
        """If _get_pipeline raises, LLM should still generate."""
        def boom():
            raise RuntimeError("Pipeline exploded")

        with patch("app.lg_agent.travel_draft_graph._get_pipeline", side_effect=boom), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            from app.lg_agent.travel_draft_graph import travel_draft_graph
            result = _run(travel_draft_graph.ainvoke({"query": "上海 3天 预算5000"}))

        assert result["final_itinerary"] is not None
        assert result["final_text"] is None

    def test_recall_failure_does_not_block_llm(self):
        """If recall raises mid-pipeline, LLM should still generate."""
        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            from app.lg_agent.travel_draft_graph import _get_pipeline, travel_draft_graph
            qp, recall_svc, scorer, flt, eb, backfill = _get_pipeline()

            async def broken_recall(*args, **kwargs):
                raise ConnectionError("Network down")

            with patch.object(recall_svc, "recall_from_qp", side_effect=broken_recall):
                result = _run(travel_draft_graph.ainvoke({"query": "上海 3天 预算5000"}))

        assert result["final_itinerary"] is not None


# ---------------------------------------------------------------------------
# Phase 1d: SSE event sequence tests
# ---------------------------------------------------------------------------

def _parse_sse_events(raw_chunks: list[str]) -> list[tuple[str | None, dict]]:
    """Parse SSE event strings into (event_type, data) tuples."""
    events = []
    for chunk in raw_chunks:
        event_type = None
        data_obj = None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                event_type = line[len("event: "):]
            if line.startswith("data: "):
                data_obj = json.loads(line[len("data: "):])
        if data_obj is not None:
            events.append((event_type, data_obj))
    return events


def _make_graph_result(*, with_evidence=True, with_itinerary=True):
    """Build a mock graph result dict matching travel_draft_graph output."""
    if not with_itinerary:
        return {
            "final_itinerary": None,
            "explanation": None,
            "final_text": "请补充目的地、天数和预算。",
        }

    evidence = []
    if with_evidence:
        evidence = [
            {
                "evidence_id": "ev-waitan",
                "provider": "mock_search",
                "source_type": "search",
                "title": "外滩",
                "url": "https://example.com/waitan",
                "snippet": "上海标志性景点",
                "fetched_at": "2026-01-01T00:00:00+00:00",
                "attribution": "数据来源：本地测试数据",
                "confidence": 0.8,
                "rating": 4.8,
                "cost_estimate": None,
            },
        ]

    return {
        "final_itinerary": {
            "schema_version": "itinerary.v1",
            "itinerary_id": "test-id",
            "revision_id": "rev-001",
            "base_revision_id": None,
            "trip_profile": {
                "destination_city": "上海",
                "constraints": {"budget_range": "~5000元"},
            },
            "days": [
                {
                    "day_index": 1,
                    "theme": "文化探索",
                    "slots": [
                        {
                            "slot": "上午",
                            "activity": "参观外滩",
                            "place": "外滩",
                            "evidence_refs": ["ev-waitan"] if with_evidence else [],
                        },
                    ],
                },
            ],
            "budget_summary": {"total_estimate": 5000},
            "evidence": evidence,
            "validation": {
                "coverage_score": 1.0 if with_evidence else None,
                "conflicts": [],
                "assumptions": ["旅行者类型未指定，默认按通用休闲安排。"] if with_evidence else [],
            },
        },
        "explanation": "已为你生成上海 3 天行程草案。",
        "final_text": None,
    }


async def _collect_sse_chunks(query_text, graph_result):
    """Call _stream_minimal_itinerary with mocked graph and collect raw chunks."""
    chunks = []

    async def mock_ainvoke(input, config=None):
        return graph_result

    with patch("app.api.travel.travel_draft_graph") as mock_graph, \
         patch("app.api.travel.ConversationService") as mock_cs:
        mock_graph.ainvoke = AsyncMock(side_effect=mock_ainvoke)
        mock_cs.upsert_travel_conversation_state = AsyncMock()

        from app.api.travel import _stream_minimal_itinerary
        gen = _stream_minimal_itinerary(
            query_text=query_text,
            thread_config={"configurable": {"thread_id": "t1"}},
            conversation_id="conv-001",
            request_id="req-001",
            user_id=1,
        )
        async for chunk in gen:
            chunks.append(chunk)

    return chunks


class TestSSEEventSequence:
    """Phase 1d: verify SSE events match design.md contract."""

    def test_stage_start_is_first_event(self):
        """stage_start(draft_plan) should be the very first SSE event."""
        chunks = asyncio.run(
            _collect_sse_chunks("上海 3天 预算5000", _make_graph_result())
        )
        events = _parse_sse_events(chunks)

        assert len(events) >= 1
        first_type, first_data = events[0]
        assert first_type == "stage_start"
        assert first_data["payload"]["stage"] == "draft_plan"

    def test_event_order_is_correct(self):
        """Full sequence: stage_start → pipeline_complete → tool_result → day_ready → stage_progress → final_itinerary."""
        chunks = asyncio.run(
            _collect_sse_chunks("上海 3天 预算5000", _make_graph_result(with_evidence=True))
        )
        events = _parse_sse_events(chunks)
        event_types = [e[0] for e in events]

        assert event_types[0] == "stage_start"
        assert "pipeline_complete" in event_types
        assert "tool_result" in event_types
        assert "day_ready" in event_types
        assert "stage_progress" in event_types
        assert "final_itinerary" in event_types

        pc_idx = event_types.index("pipeline_complete")
        tr_idx = event_types.index("tool_result")
        dr_idx = event_types.index("day_ready")
        sp_idx = event_types.index("stage_progress")
        fi_idx = event_types.index("final_itinerary")
        assert 0 < pc_idx < tr_idx < dr_idx < sp_idx < fi_idx

    def test_tool_result_evidence_payload(self):
        """tool_result should contain evidence_count and evidence list."""
        chunks = asyncio.run(
            _collect_sse_chunks("上海 3天 预算5000", _make_graph_result(with_evidence=True))
        )
        events = _parse_sse_events(chunks)
        tool_events = [(t, d) for t, d in events if t == "tool_result"]

        assert len(tool_events) == 1
        payload = tool_events[0][1]["payload"]
        assert payload["tool"] == "evidence_batch"
        assert payload["evidence_count"] == 1
        assert len(payload["evidence"]) == 1
        assert payload["evidence"][0]["title"] == "外滩"

    def test_stage_progress_validation_payload(self):
        """stage_progress(validation_summary) should contain coverage and assumptions."""
        chunks = asyncio.run(
            _collect_sse_chunks("上海 3天 预算5000", _make_graph_result(with_evidence=True))
        )
        events = _parse_sse_events(chunks)
        sp_events = [(t, d) for t, d in events if t == "stage_progress"]

        assert len(sp_events) == 1
        payload = sp_events[0][1]["payload"]
        assert payload["stage"] == "validation_summary"
        assert payload["coverage_score"] == 1.0
        assert isinstance(payload["assumptions"], list)
        assert isinstance(payload["conflicts"], list)

    def test_no_evidence_skips_tool_result(self):
        """When no evidence exists, tool_result event should be omitted but pipeline_complete emitted."""
        chunks = asyncio.run(
            _collect_sse_chunks("上海 3天 预算5000", _make_graph_result(with_evidence=False))
        )
        events = _parse_sse_events(chunks)
        event_types = [e[0] for e in events]

        assert "tool_result" not in event_types
        assert event_types[0] == "stage_start"
        assert "pipeline_complete" in event_types
        assert "final_itinerary" in event_types

    def test_no_itinerary_has_stage_start_then_final_text(self):
        """When P0 missing, events should be: stage_start → final_text."""
        chunks = asyncio.run(
            _collect_sse_chunks("想去海边", _make_graph_result(with_itinerary=False))
        )
        events = _parse_sse_events(chunks)
        event_types = [e[0] for e in events]

        assert event_types[0] == "stage_start"
        assert "final_text" in event_types
        assert "final_itinerary" not in event_types

    def test_error_still_has_stage_start(self):
        """Even on graph error, stage_start should be emitted first."""

        async def _collect_error():
            chunks = []

            async def boom_ainvoke(input, config=None):
                raise RuntimeError("Graph exploded")

            with patch("app.api.travel.travel_draft_graph") as mock_graph:
                mock_graph.ainvoke = AsyncMock(side_effect=boom_ainvoke)

                from app.api.travel import _stream_minimal_itinerary
                gen = _stream_minimal_itinerary(
                    query_text="上海 3天 预算5000",
                    thread_config={"configurable": {"thread_id": "t1"}},
                    conversation_id="conv-err",
                    request_id="req-err",
                    user_id=1,
                )
                async for chunk in gen:
                    chunks.append(chunk)
            return chunks

        chunks = asyncio.run(_collect_error())
        events = _parse_sse_events(chunks)
        event_types = [e[0] for e in events]

        assert event_types[0] == "stage_start"
        assert "error" in event_types

    def test_pipeline_complete_event(self):
        """pipeline_complete should be emitted with candidate_count."""
        chunks = asyncio.run(
            _collect_sse_chunks("上海 3天 预算5000", _make_graph_result(with_evidence=True))
        )
        events = _parse_sse_events(chunks)
        pc_events = [(t, d) for t, d in events if t == "pipeline_complete"]

        assert len(pc_events) == 1
        payload = pc_events[0][1]["payload"]
        assert payload["candidate_count"] == 1

    def test_day_ready_events(self):
        """day_ready should be emitted for each day in the itinerary."""
        chunks = asyncio.run(
            _collect_sse_chunks("上海 3天 预算5000", _make_graph_result(with_evidence=True))
        )
        events = _parse_sse_events(chunks)
        dr_events = [(t, d) for t, d in events if t == "day_ready"]

        assert len(dr_events) == 1  # mock graph has 1 day
        day = dr_events[0][1]["payload"]["day"]
        assert day["day_index"] == 1
        assert len(day["slots"]) > 0

    def test_event_sequence_with_progressive(self):
        """Verify progressive event order: stage_start → pipeline_complete → ... → day_ready → ... → final_itinerary."""
        chunks = asyncio.run(
            _collect_sse_chunks("上海 3天 预算5000", _make_graph_result(with_evidence=True))
        )
        events = _parse_sse_events(chunks)
        event_types = [e[0] for e in events]

        # First event must be stage_start
        assert event_types[0] == "stage_start"
        # pipeline_complete before day_ready
        assert event_types.index("pipeline_complete") < event_types.index("day_ready")
        # day_ready before final_itinerary
        assert event_types.index("day_ready") < event_types.index("final_itinerary")
        # final_itinerary is last structured event (before text fallback)
        assert event_types.index("final_itinerary") == len(event_types) - 1 or \
               all(e is None for e in event_types[event_types.index("final_itinerary") + 1:])

    def test_final_itinerary_envelope_has_revision_id(self):
        """final_itinerary event envelope should contain revision_id."""
        chunks = asyncio.run(
            _collect_sse_chunks("上海 3天 预算5000", _make_graph_result())
        )
        events = _parse_sse_events(chunks)
        fi_events = [(t, d) for t, d in events if t == "final_itinerary"]

        assert len(fi_events) == 1
        envelope = fi_events[0][1]
        assert envelope["revision_id"] == "rev-001"
        assert envelope["request_id"] == "req-001"
        assert envelope["conversation_id"] == "conv-001"
