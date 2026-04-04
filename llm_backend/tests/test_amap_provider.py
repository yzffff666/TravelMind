"""Tests for Amap (高德地图) providers.

All HTTP calls are mocked — no real API quota is consumed.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.providers.amap_provider import (
    AmapMapProvider,
    AmapSearchProvider,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


FAKE_AMAP_RESPONSE = {
    "status": "1",
    "count": "3",
    "pois": [
        {
            "id": "B0FFGC1GK0",
            "name": "外滩",
            "type": "风景名胜;风景名胜;国家级景点",
            "address": "中山东一路",
            "location": "121.490317,31.240018",
            "cityname": "上海市",
            "adname": "黄浦区",
            "tel": "021-33761234",
            "photos": [
                {"url": "https://example.com/photo1.jpg"},
                {"url": "https://example.com/photo2.jpg"},
            ],
            "biz_ext": {"rating": "4.8", "cost": "0"},
        },
        {
            "id": "B0FFGC2AB1",
            "name": "东方明珠广播电视塔",
            "type": "风景名胜;风景名胜;观光塔",
            "address": "世纪大道1号",
            "location": "121.499718,31.239703",
            "cityname": "上海市",
            "adname": "浦东新区",
            "tel": "021-58791888",
            "photos": [],
            "biz_ext": {"rating": "4.5", "cost": "180"},
        },
        {
            "id": "B0FFGC3CD2",
            "name": "豫园",
            "type": "风景名胜;公园;公园",
            "address": "安仁街218号",
            "location": "121.492147,31.227290",
            "cityname": "上海市",
            "adname": "黄浦区",
            "tel": "",
            "photos": [],
            "biz_ext": {"rating": "4.6", "cost": "40"},
        },
    ],
}

FAKE_EMPTY_RESPONSE = {
    "status": "1",
    "count": "0",
    "pois": [],
}

FAKE_ERROR_RESPONSE = {
    "status": "0",
    "info": "INVALID_USER_KEY",
    "infocode": "10001",
}


def _mock_httpx(response_data):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestAmapSearchProvider:
    def test_name(self):
        sp = AmapSearchProvider("fake-key")
        assert sp.name == "amap_search"

    def test_search_parses_pois(self):
        sp = AmapSearchProvider("fake-key")
        with patch("app.services.providers.amap_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_AMAP_RESPONSE)
            resp = _run(sp.search(query="上海 景点"))

        assert len(resp.candidates) == 3
        assert resp.degraded is False

        bund = resp.candidates[0]
        assert bund.title == "外滩"
        assert bund.source == "amap_search"
        assert bund.extra["lat"] == 31.240018
        assert bund.extra["lng"] == 121.490317
        assert bund.extra["rating"] == 4.8
        assert bund.extra["city"] == "上海市"
        assert len(bund.extra["photos"]) == 2

    def test_search_cost_parsed(self):
        sp = AmapSearchProvider("fake-key")
        with patch("app.services.providers.amap_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_AMAP_RESPONSE)
            resp = _run(sp.search(query="上海"))

        pearl = resp.candidates[1]
        assert pearl.extra["cost_estimate"] == 180.0

    def test_search_tags_from_type(self):
        sp = AmapSearchProvider("fake-key")
        with patch("app.services.providers.amap_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_AMAP_RESPONSE)
            resp = _run(sp.search(query="上海"))

        bund = resp.candidates[0]
        assert any("风景名胜" in t for t in bund.tags)

    def test_search_respects_top_k(self):
        sp = AmapSearchProvider("fake-key")
        with patch("app.services.providers.amap_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_AMAP_RESPONSE)
            resp = _run(sp.search(query="上海", top_k=2))

        assert len(resp.candidates) <= 2

    def test_search_api_error_degrades(self):
        sp = AmapSearchProvider("fake-key")
        with patch("app.services.providers.amap_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_ERROR_RESPONSE)
            resp = _run(sp.search(query="上海"))

        assert resp.degraded is True
        assert len(resp.candidates) == 0

    def test_search_empty_results(self):
        sp = AmapSearchProvider("fake-key")
        with patch("app.services.providers.amap_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_EMPTY_RESPONSE)
            resp = _run(sp.search(query="不存在的地方"))

        assert len(resp.candidates) == 0

    def test_extract_city(self):
        assert AmapSearchProvider._extract_city("上海市 美食") == "上海市"
        assert AmapSearchProvider._extract_city("北京 景点") == "北京"


class TestAmapMapProvider:
    def test_name(self):
        mp = AmapMapProvider("fake-key")
        assert mp.name == "amap_map"

    def test_nearby_parses_pois(self):
        mp = AmapMapProvider("fake-key")
        with patch("app.services.providers.amap_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_AMAP_RESPONSE)
            resp = _run(mp.nearby_poi(city="上海", keywords=["景点"]))

        assert len(resp.candidates) == 3
        assert resp.degraded is False
        assert resp.candidates[0].source == "amap_map"

    def test_nearby_empty_degrades(self):
        mp = AmapMapProvider("fake-key")
        with patch("app.services.providers.amap_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_EMPTY_RESPONSE)
            resp = _run(mp.nearby_poi(city="不存在", keywords=[]))

        assert resp.degraded is True

    def test_nearby_api_error_degrades(self):
        mp = AmapMapProvider("fake-key")
        with patch("app.services.providers.amap_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_ERROR_RESPONSE)
            resp = _run(mp.nearby_poi(city="上海", keywords=["美食"]))

        assert resp.degraded is True


class TestFactoryWithAmap:
    def test_amap_registered_when_key_present(self):
        with patch("app.services.providers.factory._get_key") as mock_get:
            mock_get.side_effect = lambda s, e: "amap-key" if "AMAP" in s else None
            from app.services.providers.factory import build_registry
            reg = build_registry(include_mock_fallback=False)

        names = [p.name for p in reg.search_providers]
        assert "amap_search" in names

    def test_amap_has_highest_priority(self):
        with patch("app.services.providers.factory._get_key") as mock_get:
            mock_get.return_value = "some-key"
            from app.services.providers.factory import build_registry
            reg = build_registry(include_mock_fallback=True)

        search_names = [p.name for p in reg.search_providers]
        assert search_names[0] == "amap_search"
