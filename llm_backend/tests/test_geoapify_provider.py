"""Tests for Geoapify low-cost global providers.

All HTTP calls are mocked, so these tests do not consume Geoapify quota.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.services.providers.geoapify_provider as geoapify_provider
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
def _allow_geoapify_live_for_mocked_http_tests(tmp_path):
    with patch("app.services.providers.geoapify_provider._live_enabled", return_value=True), \
            patch("app.services.providers.geoapify_provider._cache_enabled", return_value=False), \
            patch("app.services.providers.geoapify_provider._budget_state_dir", return_value=tmp_path), \
            patch("app.services.providers.geoapify_provider._daily_live_limit", return_value=0):
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
                "city": "Phuket",
                "suburb": "Talat Yai",
                "district": "Mueang Phuket",
                "county": "Mueang Phuket District",
                "municipality": "Phuket City Municipality",
                "state": "Phuket",
                "state_code": "83",
                "country": "Thailand",
                "country_code": "th",
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

    def test_search_city_uses_structured_city_parameter_for_disambiguation(self):
        sp = GeoapifySearchProvider("fake-key")
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx(FAKE_GEOCODE_RESPONSE)
            response = _run(sp.search_city(city="Oaxaca", top_k=5))

        params = mock_cls.return_value.get.await_args.kwargs["params"]
        assert params["city"] == "Oaxaca"
        assert "text" not in params
        assert len(response.candidates) == 2

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

    def test_search_daily_budget_skips_live_on_cache_miss(self):
        sp = GeoapifySearchProvider("fake-key")
        with patch(
            "app.services.providers.geoapify_provider._budget_skip_source",
            return_value="budget_exhausted",
        ), patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            resp = _run(sp.search(query="Phuket"))

        assert resp.candidates == []
        assert resp.degraded is True
        assert resp.meta["cache_source"] == "budget_exhausted"
        assert resp.errors
        assert resp.errors[0].code == ProviderErrorCode.RATE_LIMIT
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

    def test_search_rate_limit_records_budget_cooldown(self):
        sp = GeoapifySearchProvider("fake-key")
        with patch("app.services.providers.geoapify_provider._rate_limit_cooldown_seconds", return_value=60), \
                patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_status_error(429, {"message": "Quota exceeded"})

            with pytest.raises(GeoapifyHTTPError):
                _run(sp.search(query="Phuket"))

        state = geoapify_provider._read_budget_state()
        assert state["live_call_count"] == 1
        assert state["cooldown_until_epoch"] > 0
        assert "Quota exceeded" in state["last_error"]


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

    def test_generic_travel_keywords_use_categories_without_name_filter(self):
        mp = GeoapifyMapProvider("fake-key", radius_meters=40000)
        city_center = {
            "results": [{"name": "Hobart", "formatted": "Hobart, Australia", "lat": -42.8825, "lon": 147.3281}]
        }
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_sequence(
                [city_center, FAKE_PLACES_RESPONSE]
            )
            _run(
                mp.nearby_poi(
                    city="Hobart",
                    keywords=["文化景点", "博物馆", "历史街区", "景点", "公园"],
                    top_k=10,
                )
            )

        assert mock_cls.return_value.get.await_count == 2
        places_call = mock_cls.return_value.get.await_args_list[1]
        assert places_call.args[0].endswith("/v2/places")
        places_params = places_call.kwargs["params"]
        categories = set(places_params["categories"].split(","))
        assert "name" not in places_params
        assert {"tourism", "entertainment.museum", "entertainment.culture", "leisure.park"} <= categories
        assert places_params["filter"] == "circle:147.3281,-42.8825,40000"
        assert places_params["lang"] == "en"

    def test_explicit_named_poi_keeps_places_name_filter(self):
        mp = GeoapifyMapProvider("fake-key")
        city_center = {
            "results": [{"name": "Valletta", "formatted": "Valletta, Malta", "lat": 35.8989, "lon": 14.5146}]
        }
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_sequence(
                [city_center, FAKE_EMPTY_RESPONSE, FAKE_PLACES_RESPONSE]
            )
            _run(
                mp.nearby_poi(
                    city="Valletta",
                    keywords=["Upper Barrakka Gardens"],
                    top_k=10,
                )
            )

        places_params = mock_cls.return_value.get.await_args_list[2].kwargs["params"]
        assert places_params["name"] == "Upper Barrakka Gardens"

    def test_places_candidate_preserves_locality_hierarchy(self):
        mp = GeoapifyMapProvider("fake-key")
        city_center = {
            "results": [{"name": "Phuket", "formatted": "Phuket, Thailand", "lat": 7.8804, "lon": 98.3923}]
        }
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_sequence(
                [city_center, FAKE_EMPTY_RESPONSE, FAKE_PLACES_RESPONSE]
            )
            response = _run(mp.nearby_poi(city="Phuket", keywords=["Old Town"], top_k=3))

        extra = response.candidates[0].extra
        assert extra["suburb"] == "Talat Yai"
        assert extra["district"] == "Mueang Phuket"
        assert extra["county"] == "Mueang Phuket District"
        assert extra["municipality"] == "Phuket City Municipality"
        assert extra["state"] == "Phuket"
        assert extra["state_code"] == "83"
        assert extra["country_code"] == "th"
        assert "Phuket" in extra["locality_terms"]

    def test_city_center_filters_city_results_and_prefers_popular_global_match(self):
        mp = GeoapifyMapProvider("fake-key", radius_meters=40000)
        ambiguous_hobart = {
            "results": [
                {
                    "name": "Hobart",
                    "city": "Hobart",
                    "state": "Indiana",
                    "country": "United States",
                    "result_type": "city",
                    "lat": 41.5323,
                    "lon": -87.255,
                    "rank": {"popularity": 3.3736, "importance": 0.4348},
                },
                {
                    "name": "Hobart",
                    "city": "Hobart",
                    "state": "Tasmania",
                    "country": "Australia",
                    "result_type": "city",
                    "lat": -42.8825,
                    "lon": 147.3281,
                    "rank": {"popularity": 4.0192, "importance": 0.6233},
                },
            ]
        }
        with patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_httpx_sequence(
                [ambiguous_hobart, FAKE_PLACES_RESPONSE]
            )
            _run(
                mp.nearby_poi(
                    city="Hobart",
                    keywords=["文化景点", "博物馆", "公园"],
                    top_k=10,
                )
            )

        center_params = mock_cls.return_value.get.await_args_list[0].kwargs["params"]
        places_params = mock_cls.return_value.get.await_args_list[1].kwargs["params"]
        assert "type" not in center_params
        assert center_params["limit"] == 5
        assert places_params["filter"] == "circle:147.3281,-42.8825,40000"

    def test_city_center_budget_exhaustion_is_reported_as_provider_error(self):
        mp = GeoapifyMapProvider("fake-key")
        with patch(
            "app.services.providers.geoapify_provider._budget_skip_source",
            return_value="budget_exhausted",
        ), patch("app.services.providers.geoapify_provider.httpx.AsyncClient") as mock_cls:
            response = _run(
                mp.nearby_poi(
                    city="Hobart",
                    keywords=["景点", "博物馆", "公园"],
                    top_k=10,
                )
            )

        assert response.candidates == []
        assert response.degraded is True
        assert response.meta["cache_source"] == "budget_exhausted"
        assert response.errors
        assert response.errors[0].code == ProviderErrorCode.RATE_LIMIT
        mock_cls.assert_not_called()

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
    def test_factory_uses_geoapify_geocoding_only_for_resolution_not_general_search(self):
        with patch("app.services.providers.factory._get_key") as mock_get:
            mock_get.side_effect = lambda s, e: {
                "AMAP_API_KEY": "amap-key",
                "GEOAPIFY_KEY": "geoapify-key",
                "SERPAPI_KEY": "serp-key",
            }.get(s)
            reg = build_registry(include_mock_fallback=False)

        assert [p.name for p in reg.search_providers] == [
            "amap_search",
            "serp_search",
        ]
        assert [p.name for p in reg.map_providers] == [
            "amap_map",
            "geoapify_map",
            "serp_map",
        ]

    def test_cost_mode_cheap_keeps_geoapify_map_but_skips_general_search_and_serpapi(self):
        with patch("app.services.providers.factory._get_key") as mock_get, \
                patch("app.services.providers.factory._provider_cost_mode", return_value="cheap"):
            mock_get.side_effect = lambda s, e: {
                "GEOAPIFY_KEY": "geoapify-key",
                "SERPAPI_KEY": "serp-key",
            }.get(s)
            reg = build_registry(include_mock_fallback=False)

        assert [p.name for p in reg.search_providers] == []
        assert [p.name for p in reg.map_providers] == ["geoapify_map"]
        assert reg.map_providers[0]._radius_meters == 40000


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
        assert any("Geoapify HTTP 429" in error.message for error in result.errors)
        assert geoapify_provider._read_budget_state()["cooldown_until_epoch"] > 0
