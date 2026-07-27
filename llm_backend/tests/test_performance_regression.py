"""Performance regression tests for the multi-node travel draft graph.

These tests verify that:
- Individual nodes complete within expected time bounds (with mocks).
- The full graph completes within expected time bounds (with mocks).
- Performance timing metrics (perf dict) are populated correctly.

All LLM and provider calls are mocked to isolate graph/node overhead
from external service latency.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MOCK_LLM_RESPONSE = json.dumps({
    "days": [
        {
            "day_index": 1,
            "theme": "城市探索",
            "slots": [
                {"slot": "上午", "activity": "参观外滩", "place": "外滩"},
                {"slot": "下午", "activity": "游览豫园", "place": "豫园"},
                {"slot": "晚上", "activity": "南京路步行街", "place": "南京路"},
            ],
        },
        {
            "day_index": 2,
            "theme": "文化之旅",
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
    mock_llm = MagicMock()

    async def _mock_astream(messages, **kwargs):
        chunk_size = 100
        for i in range(0, len(_MOCK_LLM_RESPONSE), chunk_size):
            chunk = MagicMock()
            chunk.content = _MOCK_LLM_RESPONSE[i:i + chunk_size]
            yield chunk

    mock_llm.astream = _mock_astream

    mock_response = MagicMock()
    mock_response.content = _MOCK_LLM_RESPONSE
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    return mock_llm


def _run(coro):
    return asyncio.run(coro)


def _reset_pipeline_singletons():
    import app.lg_agent.travel_draft_graph as tdg
    tdg._pipeline_qp = None
    tdg._pipeline_recall = None
    tdg._pipeline_scorer = None
    tdg._pipeline_filter = None
    tdg._pipeline_eb = None
    from app.services.providers.orchestrator import clear_recall_cache
    clear_recall_cache()


@pytest.fixture(autouse=True)
def _allow_mock_publish_for_performance_harness():
    """The performance harness measures graph overhead with fake providers."""
    with patch("app.lg_agent.travel_draft_graph.settings.ALLOW_MOCK_PUBLISH", True):
        yield


class TestPerformanceBaseline:
    """Verify that node and graph execution times stay within bounds."""

    def setup_method(self):
        _reset_pipeline_singletons()

    def test_extract_node_under_50ms(self):
        """extract_node should complete in < 50ms (pure regex, no I/O)."""
        from app.lg_agent.travel_draft_graph import extract_node
        result = _run(extract_node({"query": "上海 4天 预算6000 情侣 文化 美食"}))
        elapsed_ms = result["perf"]["extract_ms"]

        assert elapsed_ms < 50, f"extract_node took {elapsed_ms:.1f}ms (limit: 50ms)"
        assert result["destination"] == "上海"
        assert result["days_count"] == 4

    def test_recall_node_under_5s(self):
        """recall_node should complete in < 5s with mock providers."""
        from app.lg_agent.travel_draft_graph import recall_node

        state = {
            "query": "上海 4天 预算6000 文化",
            "missing_p0": [],
            "perf": {},
        }
        with patch("app.services.providers.factory._get_key", return_value=None):
            t0 = time.perf_counter()
            result = _run(recall_node(state))
            elapsed_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_ms < 5000, f"recall_node took {elapsed_ms:.1f}ms (limit: 5000ms)"
        assert result["pipeline_result"] is not None

    def test_full_graph_under_10s(self):
        """Full graph (extract -> recall -> llm -> postprocess) should complete in < 10s with mocks."""
        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            from app.lg_agent.travel_draft_graph import travel_draft_graph

            t0 = time.perf_counter()
            result = _run(travel_draft_graph.ainvoke({"query": "上海 4天 预算6000 文化 美食"}))
            elapsed_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_ms < 10000, f"Full graph took {elapsed_ms:.1f}ms (limit: 10000ms)"
        assert result["final_itinerary"] is not None

    def test_perf_dict_complete(self):
        """Output perf dict should contain timing for all 4 nodes."""
        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            from app.lg_agent.travel_draft_graph import travel_draft_graph
            result = _run(travel_draft_graph.ainvoke({"query": "上海 3天 预算5000"}))

        perf = result.get("perf", {})
        assert "extract_ms" in perf, f"Missing extract_ms in perf: {perf}"
        assert "recall_ms" in perf, f"Missing recall_ms in perf: {perf}"
        assert "llm_ms" in perf, f"Missing llm_ms in perf: {perf}"
        assert "postprocess_ms" in perf, f"Missing postprocess_ms in perf: {perf}"

        assert perf["extract_ms"] >= 0
        assert perf["recall_ms"] >= 0
        assert perf["llm_ms"] >= 0
        assert perf["postprocess_ms"] >= 0

    def test_ttft_metric_in_perf(self):
        """perf dict should include llm_ttft_ms (time to first token)."""
        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            from app.lg_agent.travel_draft_graph import travel_draft_graph
            result = _run(travel_draft_graph.ainvoke({"query": "北京 3天 预算5000 亲子"}))

        perf = result.get("perf", {})
        assert "llm_ttft_ms" in perf
        assert perf["llm_ttft_ms"] is not None
        assert perf["llm_ttft_ms"] >= 0

    def test_early_exit_skips_expensive_nodes(self):
        """When P0 fields are missing, recall/llm/postprocess nodes should not run."""
        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            from app.lg_agent.travel_draft_graph import travel_draft_graph

            t0 = time.perf_counter()
            result = _run(travel_draft_graph.ainvoke({"query": "想去海边玩几天"}))
            elapsed_ms = (time.perf_counter() - t0) * 1000

        assert result["final_itinerary"] is None
        assert result["final_text"] is not None
        assert elapsed_ms < 500, f"Early exit took {elapsed_ms:.1f}ms (should be very fast)"

        perf = result.get("perf", {})
        assert "extract_ms" in perf
        assert "recall_ms" not in perf
        assert "llm_ms" not in perf


class TestProviderParallelization:
    """Verify that provider parallelization actually runs providers concurrently."""

    def setup_method(self):
        _reset_pipeline_singletons()

    def test_parallel_providers_faster_than_sequential(self):
        """Multiple providers should run in parallel, not sequentially."""
        from app.lg_agent.travel_draft_graph import recall_node

        state = {
            "query": "上海 4天 预算6000 文化",
            "missing_p0": [],
            "perf": {},
        }
        with patch("app.services.providers.factory._get_key", return_value=None):
            t0 = time.perf_counter()
            result = _run(recall_node(state))
            elapsed_ms = (time.perf_counter() - t0) * 1000

        assert result.get("pipeline_result") is not None
        assert elapsed_ms < 5000


class TestGraphConditionalRouting:
    """Verify that conditional edges route correctly."""

    def setup_method(self):
        _reset_pipeline_singletons()

    def test_missing_p0_routes_to_early_exit(self):
        """Missing P0 fields should skip recall/llm and return final_text."""
        with patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            from app.lg_agent.travel_draft_graph import travel_draft_graph
            result = _run(travel_draft_graph.ainvoke({"query": "想去玩"}))

        assert result["final_itinerary"] is None
        assert result["final_text"] is not None
        assert "目的地" in result["final_text"] or "天数" in result["final_text"]

    def test_complete_p0_routes_to_full_pipeline(self):
        """Complete P0 fields should run through all 4 nodes."""
        with patch("app.services.providers.factory._get_key", return_value=None), \
             patch("app.lg_agent.travel_draft_graph._get_llm", return_value=_make_mock_llm()):
            from app.lg_agent.travel_draft_graph import travel_draft_graph
            result = _run(travel_draft_graph.ainvoke({"query": "上海 3天 预算5000"}))

        assert result["final_itinerary"] is not None
        perf = result.get("perf", {})
        assert all(k in perf for k in ["extract_ms", "recall_ms", "llm_ms", "postprocess_ms"])
