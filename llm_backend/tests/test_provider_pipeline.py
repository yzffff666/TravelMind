"""Tests for T-M2-002a (call policy), T-M2-002b (orchestrator), T-M2-006 (mock providers).

Covers:
- ProviderCallPolicy configuration
- MockSearchProvider / MockMapProvider fixture results
- ProviderOrchestrator recall with budget, timeout, degradation
- Deduplication of candidates
- Assumptions generation on failure
"""

import asyncio

from app.services.providers.base import (
    ProviderCallContext,
    ProviderCandidate,
    ProviderErrorCode,
    ProviderResponse,
    SearchProvider,
)
from app.services.providers.call_policy import (
    DEFAULT_POLICY,
    ProviderCallPolicy,
    ProviderType,
)
from app.services.providers.mock_providers import MockMapProvider, MockSearchProvider
from app.services.providers.orchestrator import ProviderOrchestrator
from app.services.providers.registry import ProviderRegistry


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ======================== T-M2-002a: CallPolicy ========================


class TestCallPolicy:
    def test_default_policy_values(self):
        p = DEFAULT_POLICY
        assert p.max_calls_per_request == 6
        assert p.timeout_seconds == 10.0
        assert p.search_enabled is True
        assert p.map_enabled is True
        assert p.weather_enabled is False
        assert p.review_enabled is False

    def test_is_enabled(self):
        p = ProviderCallPolicy(search_enabled=False)
        assert p.is_enabled(ProviderType.SEARCH) is False
        assert p.is_enabled(ProviderType.MAP) is True

    def test_provider_priority_order(self):
        p = DEFAULT_POLICY
        assert p.provider_priority[0] == ProviderType.SEARCH
        assert p.provider_priority[1] == ProviderType.MAP

    def test_custom_policy(self):
        p = ProviderCallPolicy(
            max_calls_per_request=2,
            timeout_seconds=5.0,
            top_k_search=5,
        )
        assert p.max_calls_per_request == 2
        assert p.top_k_search == 5


# ======================== T-M2-006: Mock Providers ========================


class TestMockSearchProvider:
    def test_search_known_city(self):
        sp = MockSearchProvider()
        assert sp.name == "mock_search"
        resp = _run(sp.search(query="上海 文化 美食"))
        assert isinstance(resp, ProviderResponse)
        assert len(resp.candidates) > 0
        assert all(isinstance(c, ProviderCandidate) for c in resp.candidates)

    def test_search_unknown_city_returns_degraded(self):
        sp = MockSearchProvider()
        resp = _run(sp.search(query="伦敦 3天"))
        assert resp.degraded is True
        assert len(resp.candidates) == 0

    def test_search_respects_top_k(self):
        sp = MockSearchProvider()
        resp = _run(sp.search(query="北京 旅行", top_k=3))
        assert len(resp.candidates) <= 3

    def test_candidate_fields(self):
        sp = MockSearchProvider()
        resp = _run(sp.search(query="成都"))
        c = resp.candidates[0]
        assert c.candidate_id
        assert c.source == "mock_search"
        assert c.title
        assert isinstance(c.tags, list)
        assert isinstance(c.extra, dict)

    def test_all_fixture_cities(self):
        sp = MockSearchProvider()
        for city in ["上海", "北京", "成都"]:
            resp = _run(sp.search(query=city))
            assert len(resp.candidates) > 0, f"No results for {city}"


class TestMockMapProvider:
    def test_map_known_city(self):
        mp = MockMapProvider()
        assert mp.name == "mock_map"
        resp = _run(mp.nearby_poi(city="上海", keywords=["景点"]))
        assert len(resp.candidates) > 0

    def test_map_unknown_city(self):
        mp = MockMapProvider()
        resp = _run(mp.nearby_poi(city="巴黎", keywords=["景点"]))
        assert resp.degraded is True
        assert len(resp.candidates) == 0

    def test_map_candidate_has_location(self):
        mp = MockMapProvider()
        resp = _run(mp.nearby_poi(city="北京", keywords=[]))
        for c in resp.candidates:
            assert "lat" in c.extra or "lng" in c.extra


# ======================== T-M2-002b: Orchestrator ========================


def _make_registry(search: bool = True, map_: bool = True) -> ProviderRegistry:
    reg = ProviderRegistry()
    if search:
        reg.register_search(MockSearchProvider())
    if map_:
        reg.register_map(MockMapProvider())
    return reg


class TestOrchestrator:
    def test_recall_returns_candidates(self):
        orch = ProviderOrchestrator(_make_registry())
        result = _run(orch.recall(query="上海 文化 美食", city="上海"))
        assert len(result.candidates) > 0
        assert result.calls_made >= 1
        assert result.degraded is False

    def test_recall_deduplicates(self):
        orch = ProviderOrchestrator(_make_registry())
        result = _run(orch.recall(query="上海", city="上海"))
        ids = [c.candidate_id for c in result.candidates]
        assert len(ids) == len(set(ids)), "Duplicate candidates found"

    def test_recall_merges_search_and_map(self):
        orch = ProviderOrchestrator(_make_registry())
        result = _run(orch.recall(query="上海", city="上海"))
        sources = {c.source for c in result.candidates}
        assert "mock_search" in sources
        assert "mock_map" in sources

    def test_recall_empty_registry_degrades(self):
        reg = ProviderRegistry()
        orch = ProviderOrchestrator(reg)
        result = _run(orch.recall(query="上海", city="上海"))
        assert result.degraded is True
        assert len(result.assumptions) > 0
        assert any("不可用" in a or "AI 知识" in a for a in result.assumptions)

    def test_call_budget_enforced(self):
        policy = ProviderCallPolicy(max_calls_per_request=1)
        reg = _make_registry()
        orch = ProviderOrchestrator(reg, policy)
        result = _run(orch.recall(query="上海", city="上海"))
        assert result.calls_made <= 1
        assert any("上限" in a for a in result.assumptions)

    def test_disabled_provider_skipped(self):
        policy = ProviderCallPolicy(search_enabled=False)
        orch = ProviderOrchestrator(_make_registry(), policy)
        result = _run(orch.recall(query="上海", city="上海"))
        sources = {c.source for c in result.candidates}
        assert "mock_search" not in sources
        assert "mock_map" in sources

    def test_timeout_produces_error_and_assumption(self):
        class SlowSearch(SearchProvider):
            @property
            def name(self) -> str:
                return "slow_search"

            async def search(self, *, query, top_k=10, context=None):
                await asyncio.sleep(999)
                return ProviderResponse()

        reg = ProviderRegistry()
        reg.register_search(SlowSearch())
        policy = ProviderCallPolicy(timeout_seconds=0.05)
        orch = ProviderOrchestrator(reg, policy)
        result = _run(orch.recall(query="上海", city="上海"))
        assert result.degraded is True
        assert any(e.code == ProviderErrorCode.TIMEOUT for e in result.errors)
        assert any("timeout" in a or "调用失败" in a for a in result.assumptions)

    def test_exception_produces_error_and_assumption(self):
        class BrokenSearch(SearchProvider):
            @property
            def name(self) -> str:
                return "broken"

            async def search(self, *, query, top_k=10, context=None):
                raise ConnectionError("network down")

        reg = ProviderRegistry()
        reg.register_search(BrokenSearch())
        orch = ProviderOrchestrator(reg)
        result = _run(orch.recall(query="上海", city="上海"))
        assert result.degraded is True
        assert len(result.errors) >= 1
        assert result.errors[0].provider_name == "broken"
        assert any("broken" in a for a in result.assumptions)

    def test_context_passed_through(self):
        ctx = ProviderCallContext(request_id="req-123", conversation_id="conv-456")
        orch = ProviderOrchestrator(_make_registry())
        result = _run(orch.recall(query="成都", city="成都", context=ctx))
        assert len(result.candidates) > 0

    def test_unknown_city_degrades_gracefully(self):
        orch = ProviderOrchestrator(_make_registry())
        result = _run(orch.recall(query="莫斯科 旅行", city="莫斯科"))
        assert result.degraded is True
        assert any("AI 知识" in a for a in result.assumptions)
