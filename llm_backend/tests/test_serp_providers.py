"""Tests for SerpAPI real providers and provider factory.

These tests verify:
- SerpApiSearchProvider / SerpApiMapProvider correctly parse SerpAPI responses
- Provider factory selects real vs mock based on key availability
- Orchestrator works end-to-end with factory-built registry

Note: tests use mocked HTTP to avoid real API calls and costs.
"""

import asyncio
import json

from unittest.mock import AsyncMock, patch, MagicMock

from app.services.providers.factory import build_registry
from app.services.providers.orchestrator import ProviderOrchestrator
from app.services.providers.serp_providers import (
    SerpApiMapProvider,
    SerpApiSearchProvider,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


FAKE_GOOGLE_RESPONSE = {
    "organic_results": [
        {
            "position": 1,
            "title": "上海旅游攻略 - 必去景点推荐",
            "link": "https://example.com/shanghai-guide",
            "snippet": "外滩、东方明珠、豫园...上海最全旅游攻略，包含美食、景点、交通指南。",
            "displayed_link": "example.com",
            "date": "2025-12-01",
        },
        {
            "position": 2,
            "title": "上海3天自由行路线",
            "link": "https://example.com/shanghai-3day",
            "snippet": "适合情侣的上海文化美食之旅，预算5000元。",
            "displayed_link": "travel.example.com",
        },
        {
            "position": 3,
            "title": "上海美食地图",
            "link": "https://example.com/shanghai-food",
            "snippet": "本帮菜、小笼包、生煎...上海必吃美食清单。",
            "displayed_link": "food.example.com",
        },
    ]
}

FAKE_MAPS_RESPONSE = {
    "local_results": [
        {
            "title": "外滩",
            "rating": 4.8,
            "reviews": 12345,
            "type": "Tourist attraction · 景点",
            "address": "上海市黄浦区中山东一路",
            "gps_coordinates": {"latitude": 31.2400, "longitude": 121.4900},
            "thumbnail": "https://example.com/bund.jpg",
            "place_id": "ChIJ_abc123",
        },
        {
            "title": "豫园",
            "rating": 4.6,
            "reviews": 8901,
            "type": "Park · 公园",
            "address": "上海市黄浦区安仁街218号",
            "gps_coordinates": {"latitude": 31.2270, "longitude": 121.4920},
            "place_id": "ChIJ_def456",
            "description": "明代古典园林，展现江南园林艺术精华",
        },
        {
            "title": "南翔馒头店",
            "rating": 4.2,
            "reviews": 3456,
            "type": "Restaurant · 餐厅",
            "address": "上海市黄浦区豫园路85号",
            "gps_coordinates": {"latitude": 31.2280, "longitude": 121.4930},
            "price": "$$",
        },
    ]
}


def _mock_httpx_get(response_data):
    """Create a mock for httpx.AsyncClient.get that returns given data."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ======================== SerpApiSearchProvider ========================


class TestSerpApiSearchProvider:
    def test_name(self):
        sp = SerpApiSearchProvider("fake-key")
        assert sp.name == "serp_search"

    def test_search_parses_results(self):
        sp = SerpApiSearchProvider("fake-key")
        with patch("app.services.providers.serp_providers.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_get(FAKE_GOOGLE_RESPONSE)
            resp = _run(sp.search(query="上海"))

        assert len(resp.candidates) == 3
        assert resp.degraded is False

        c0 = resp.candidates[0]
        assert "上海" in c0.title
        assert c0.source == "serp_search"
        assert c0.extra["url"] == "https://example.com/shanghai-guide"
        assert c0.score > resp.candidates[1].score  # position 1 > position 2

    def test_search_extracts_tags(self):
        sp = SerpApiSearchProvider("fake-key")
        with patch("app.services.providers.serp_providers.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_get(FAKE_GOOGLE_RESPONSE)
            resp = _run(sp.search(query="上海"))

        food_result = resp.candidates[2]
        assert "美食" in food_result.tags

    def test_search_respects_top_k(self):
        sp = SerpApiSearchProvider("fake-key")
        with patch("app.services.providers.serp_providers.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_get(FAKE_GOOGLE_RESPONSE)
            resp = _run(sp.search(query="上海", top_k=2))

        assert len(resp.candidates) <= 2

    def test_search_empty_results(self):
        sp = SerpApiSearchProvider("fake-key")
        with patch("app.services.providers.serp_providers.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_get({"organic_results": []})
            resp = _run(sp.search(query="xyznonexistent"))

        assert len(resp.candidates) == 0
        assert resp.degraded is False


# ======================== SerpApiMapProvider ========================


class TestSerpApiMapProvider:
    def test_name(self):
        mp = SerpApiMapProvider("fake-key")
        assert mp.name == "serp_map"

    def test_nearby_poi_parses_results(self):
        mp = SerpApiMapProvider("fake-key")
        with patch("app.services.providers.serp_providers.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_get(FAKE_MAPS_RESPONSE)
            resp = _run(mp.nearby_poi(city="上海", keywords=["景点"]))

        assert len(resp.candidates) == 3
        assert resp.degraded is False

        bund = resp.candidates[0]
        assert bund.title == "外滩"
        assert bund.source == "serp_map"
        assert bund.extra["rating"] == 4.8
        assert bund.extra["lat"] == 31.2400
        assert bund.extra["lng"] == 121.4900
        assert bund.extra["reviews_count"] == 12345

    def test_nearby_poi_tags(self):
        mp = SerpApiMapProvider("fake-key")
        with patch("app.services.providers.serp_providers.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_get(FAKE_MAPS_RESPONSE)
            resp = _run(mp.nearby_poi(city="上海", keywords=[]))

        restaurant = resp.candidates[2]
        assert "美食" in restaurant.tags

    def test_nearby_poi_score_from_rating(self):
        mp = SerpApiMapProvider("fake-key")
        with patch("app.services.providers.serp_providers.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_get(FAKE_MAPS_RESPONSE)
            resp = _run(mp.nearby_poi(city="上海", keywords=[]))

        bund = resp.candidates[0]
        assert abs(bund.score - 4.8 / 5.0) < 0.01

    def test_nearby_poi_empty_degrades(self):
        mp = SerpApiMapProvider("fake-key")
        with patch("app.services.providers.serp_providers.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_get({"local_results": []})
            resp = _run(mp.nearby_poi(city="nonexistent", keywords=[]))

        assert resp.degraded is True
        assert len(resp.candidates) == 0


# ======================== Factory ========================


class TestProviderFactory:
    def test_factory_with_no_key_uses_mock_only(self):
        with patch("app.services.providers.factory._get_serpapi_key", return_value=None):
            reg = build_registry()

        names = [p.name for p in reg.search_providers]
        assert "mock_search" in names
        assert "serp_search" not in names

    def test_factory_with_real_key_registers_both(self):
        with patch("app.services.providers.factory._get_serpapi_key", return_value="real-key-123"):
            reg = build_registry()

        search_names = [p.name for p in reg.search_providers]
        map_names = [p.name for p in reg.map_providers]
        assert "serp_search" in search_names
        assert "mock_search" in search_names
        assert "serp_map" in map_names
        assert "mock_map" in map_names
        assert search_names.index("serp_search") < search_names.index("mock_search")

    def test_factory_no_mock_fallback(self):
        with patch("app.services.providers.factory._get_serpapi_key", return_value="key"):
            reg = build_registry(include_mock_fallback=False)

        assert len(reg.search_providers) == 1
        assert reg.search_providers[0].name == "serp_search"


# ======================== E2E: Factory + Orchestrator ========================


class TestFactoryOrchestrator:
    def test_e2e_mock_fallback_recall(self):
        """With no real key, orchestrator falls back to mock data."""
        with patch("app.services.providers.factory._get_serpapi_key", return_value=None):
            reg = build_registry()

        orch = ProviderOrchestrator(reg)
        result = _run(orch.recall(query="上海 旅行", city="上海"))
        assert len(result.candidates) > 0
        sources = {c.source for c in result.candidates}
        assert "mock_search" in sources or "mock_map" in sources

    def test_e2e_real_provider_with_mock_http(self):
        """With a real key and mocked HTTP, real providers contribute."""
        with patch("app.services.providers.factory._get_serpapi_key", return_value="key-123"):
            reg = build_registry(include_mock_fallback=False)

        with patch("app.services.providers.serp_providers.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_get(FAKE_GOOGLE_RESPONSE)
            orch = ProviderOrchestrator(reg)
            result = _run(orch.recall(query="上海", city="上海"))

        assert len(result.candidates) > 0
