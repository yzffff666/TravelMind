"""Tests for Geoapify low-cost global providers.

All HTTP calls are mocked, so these tests do not consume Geoapify quota.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.providers.base import ProviderErrorCode
from app.services.providers.factory import build_registry
from app.services.providers.geoapify_provider import (
    GeoapifyHTTPError,
    GeoapifyMapProvider,
    GeoapifySearchProvider,
)
from app.services.providers.orchestrator import ProviderOrchestrator


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _allow_geoapify_live_for_mocked_http_tests():
    with patch("app.services.providers.geoapify_provider._live_enabled", return_value=True), \
            patch("app.services.providers.geoapify_provider._cache_enabled", return_value=False):
        yield


FAKE_GEOCODE_RESPONSE = {
    "results": [
        {
            "name": "Patong Beach",
            "formatted": "Patong Beach, Phuket, Thailand",
            "lat": 7.8966,
            "lon": 98.2954,
            "country": "Thailand",
            "city": "Phuket",
            "result_type": "amenity",
            "categories": ["tourism.attraction", "beach"],
            "rank": {"confidence": 0.94},
            "place_id": "geoapify-patong",
        },
        {
            "name": "Big Buddha Phuket",
            "formatted": "Karon, Phuket, Thailand",
            "lat": 7.8276,
            "lon": 98.3127,
            "country": "Thailand",
            "city": "Phuket",
            "result_type": "tourism",
            "categories": ["tourism.sights", "religion"],
            "rank": {"confidence": 0.9},
            "place_id": "geoapify-buddha",
        },
    ]
}

FAKE_EMPTY_RESPONSE = {"results": []}

FAKE_PLACES_RESPONSE = {
    "features": [
        {
            "properties": {
                "name": "Phuket Old Town",
                "formatted": "Mueang Phuket, Phuket, Thailand",
                "categories": ["tourism.sights"],
                "rank": {"popularity": 0.82},
                "place_id": "geoapify-old-town",
            },
            "geometry": {"coordinates": [98.3883, 7.8841]},
        }
    ]
}

FAKE_OLD_TOWN_MIXED_RESPONSE = {
    "results": [
        {
            "name": "Phuket City Municipality, Phuket Old Town",
            "formatted": "Phuket City Municipality, Phuket Old Town, 83000, Thailand",
            "lat": 7.8847774,
            "lon": 98.3892206,
            "categories": ["administrative"],
            "rank": {"confidence": 0.5},
        },
        {
            "name": "Beehive Phuket Old Town Hostel",
            "formatted": "Beehive Phuket Old Town Hostel, Debuk Road, Phuket Old Town, Thailand",
            "lat": 7.8864847,
            "lon": 98.3926823,
            "categories": ["accommodation.hostel"],
            "rank": {"confidence": 0.6},
        },
    ]
}


def _mock_response(response_data):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_data
    return mock_response


def _mock_httpx(response_data):
    mock_client = AsyncMock()
    mock_client.get.return_value = _mock_response(response_data)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _mock_httpx_sequence(response_data_list):
    mock_client = AsyncMock()
    mock_client.get.side_effect = [_mock_response(data) for data in response_data_list]
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _mock_httpx_status_error(status_code: int, payload: dict):
    request = httpx.Request("GET", "https://api.geoapify.com/v1/geocode/search")
    response = httpx.Response(status_code, json=payload, request=request)
    error = httpx.HTTPStatusError("bad response", request=request, response=response)

    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.raise_for_status.side_effect = error
    mock_response.json.return_value = payload
    mock_response.text = json.dumps(payload, ensure_ascii=False)

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestGeoapifySearchProvider:
    def test_name(self):
        sp = GeoapifySearchProvider("fake-key")
        assert sp.name == "geoapify_search"

    def test_search_parses_geocode_results(self):
        sp = GeoapifySearchProvider("fake-key")
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_GEOCODE_RESPONSE)
            resp = _run(sp.search(query="Phuket beaches"))

        assert len(resp.candidates) == 2
        assert resp.meta["provider_cost_tier"] == "low_cost"
        assert resp.meta["cache_source"] == "live"
        assert resp.candidates[0].title == "Patong Beach"
        assert resp.candidates[0].extra["lat"] == 7.8966
        assert resp.candidates[0].extra["lng"] == 98.2954
        assert "tourism.attraction" in resp.candidates[0].tags

    def test_search_cache_only_skips_live_on_cache_miss(self, tmp_path):
        sp = GeoapifySearchProvider("fake-key")
        with patch("app.services.providers.geoapify_provider._cache_enabled", return_value=True), \
                patch("app.services.providers.geoapify_provider._cache_dir", return_value=tmp_path), \
                patch("app.services.providers.geoapify_provider._live_enabled", return_value=False), \
                patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            resp = _run(sp.search(query="Phuket"))

        assert resp.candidates == []
        assert resp.meta["cache_source"] == "live_disabled"
        assert resp.meta["provider_cost_tier"] == "low_cost"
        mock_cls.assert_not_called()

    def test_search_http_status_error_has_structured_diagnostics(self):
        sp = GeoapifySearchProvider("fake-key")
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_status_error(
                403,
                {"message": "Invalid apiKey", "apiKey": "secret"},
            )

            with pytest.raises(GeoapifyHTTPError) as exc_info:
                _run(sp.search(query="Phuket"))

        assert exc_info.value.status_code == 403
        assert "Invalid apiKey" in exc_info.value.response_snippet
        assert "secret" not in exc_info.value.response_snippet


class TestGeoapifyMapProvider:
    def test_name(self):
        mp = GeoapifyMapProvider("fake-key")
        assert mp.name == "geoapify_map"

    def test_nearby_poi_uses_exact_geocoding_first(self):
        mp = GeoapifyMapProvider("fake-key")
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_GEOCODE_RESPONSE)
            resp = _run(mp.nearby_poi(city="Phuket", keywords=["Patong Beach"], top_k=1))

        assert len(resp.candidates) == 1
        assert resp.candidates[0].source == "geoapify_map"
        assert resp.candidates[0].title == "Patong Beach"
        assert resp.degraded is False

    def test_nearby_poi_falls_back_to_places_around_city(self):
        mp = GeoapifyMapProvider("fake-key")
        city_center = {
            "results": [{"name": "Phuket", "formatted": "Phuket, Thailand", "lat": 7.8804, "lon": 98.3923}]
        }
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_sequence(
                [city_center, FAKE_EMPTY_RESPONSE, FAKE_PLACES_RESPONSE]
            )
            resp = _run(mp.nearby_poi(city="Phuket", keywords=["Old Town"], top_k=3))

        assert len(resp.candidates) == 1
        assert resp.candidates[0].title == "Phuket Old Town"
        assert resp.candidates[0].extra["lat"] == 7.8841
        assert resp.candidates[0].extra["lng"] == 98.3883
        assert resp.meta["cache_source"] == "live+live"
        exact_params = mock_cls.return_value.get.await_args_list[1].kwargs["params"]
        assert exact_params["filter"].startswith("circle:98.3923,7.8804,")
        assert exact_params["bias"] == "proximity:98.3923,7.8804"

    def test_nearby_poi_penalizes_lodging_when_query_is_attraction(self):
        mp = GeoapifyMapProvider("fake-key")
        city_center = {
            "results": [{"name": "Phuket", "formatted": "Phuket, Thailand", "lat": 7.8804, "lon": 98.3923}]
        }
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_sequence(
                [city_center, FAKE_OLD_TOWN_MIXED_RESPONSE, {"features": []}]
            )
            resp = _run(mp.nearby_poi(city="Phuket", keywords=["Phuket Old Town"], top_k=2))

        assert resp.candidates[0].title == "Phuket City Municipality, Phuket Old Town"


class TestGeoapifyFactory:
    def test_factory_registers_geoapify_between_amap_and_serpapi(self):
        with patch("app.services.providers.factory._get_key") as mock_get:
            mock_get.side_effect = lambda s, e: {
                "AMAP_API_KEY": "amap-key",
                "GEOAPIFY_KEY": "geoapify-key",
                "SERPAPI_KEY": "serp-key",
            }.get(s)
            reg = build_registry(include_mock_fallback=False)

        assert [p.name for p in reg.search_providers] == [
            "amap_search",
            "geoapify_search",
            "serp_search",
        ]
        assert [p.name for p in reg.map_providers] == [
            "amap_map",
            "geoapify_map",
            "serp_map",
        ]

    def test_cost_mode_cheap_keeps_geoapify_but_skips_serpapi(self):
        with patch("app.services.providers.factory._get_key") as mock_get, \
                patch("app.services.providers.factory._provider_cost_mode", return_value="cheap"):
            mock_get.side_effect = lambda s, e: {
                "GEOAPIFY_KEY": "geoapify-key",
                "SERPAPI_KEY": "serp-key",
            }.get(s)
            reg = build_registry(include_mock_fallback=False)

        assert [p.name for p in reg.search_providers] == ["geoapify_search"]
        assert [p.name for p in reg.map_providers] == ["geoapify_map"]


class TestGeoapifyOrchestrator:
    def test_geoapify_http_status_maps_to_rate_limit(self):
        with patch("app.services.providers.factory._get_key") as mock_get:
            mock_get.side_effect = lambda s, e: "geoapify-key" if s == "GEOAPIFY_KEY" else None
            reg = build_registry(include_mock_fallback=False)

        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_status_error(429, {"message": "Quota exceeded"})
            orch = ProviderOrchestrator(reg)
            result = _run(orch.recall(query="Phuket", city="Phuket"))

        assert result.degraded is True
        assert result.errors
        assert {error.code for error in result.errors} == {ProviderErrorCode.RATE_LIMIT}
        assert all("Geoapify HTTP 429" in error.message for error in result.errors)
