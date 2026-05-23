"""Low-cost global POI providers backed by Geoapify.

Geoapify is used as the day-to-day overseas provider before SerpAPI.
It provides global geocoding and places data at a much lower cost tier,
while still fitting the same ProviderCandidate shape used by ranking and
backfill.

Docs:
- Geocoding: https://apidocs.geoapify.com/docs/geocoding/forward-geocoding/
- Places: https://apidocs.geoapify.com/docs/places/
"""

from __future__ import annotations

import json
import logging
import os
import re
from hashlib import md5
from pathlib import Path
from typing import Any

import httpx

from app.services.providers.base import (
    MapProvider,
    ProviderCallContext,
    ProviderCandidate,
    ProviderResponse,
    SearchProvider,
)

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
_PLACES_URL = "https://api.geoapify.com/v2/places"
_MAX_ERROR_SNIPPET_CHARS = 300
_DEFAULT_PLACE_CATEGORIES = ",".join(
    [
        "tourism",
        "catering",
        "accommodation",
        "entertainment",
        "leisure",
        "commercial",
    ]
)


class GeoapifyHTTPError(RuntimeError):
    """HTTP failure from Geoapify with structured diagnostics."""

    def __init__(self, *, status_code: int, response_snippet: str) -> None:
        self.status_code = status_code
        self.response_snippet = response_snippet
        super().__init__(f"Geoapify HTTP {status_code}: {response_snippet}")


def _candidate_id(title: str, location_hint: str) -> str:
    raw = f"geoapify-{title}-{location_hint}".strip().lower()
    return md5(raw.encode()).hexdigest()[:12]


def _cache_enabled() -> bool:
    try:
        from app.core.config import settings
        return bool(settings.GEOAPIFY_RESPONSE_CACHE_ENABLED)
    except Exception:
        raw = os.getenv("GEOAPIFY_RESPONSE_CACHE_ENABLED", "true")
        return raw.strip().lower() not in {"0", "false", "no", "off"}


def _live_enabled() -> bool:
    try:
        from app.core.config import settings
        return bool(settings.GEOAPIFY_LIVE_ENABLED)
    except Exception:
        raw = os.getenv("GEOAPIFY_LIVE_ENABLED", "true")
        return raw.strip().lower() not in {"0", "false", "no", "off"}


def _cache_dir() -> Path:
    try:
        from app.core.config import ROOT_DIR, settings
        return Path(ROOT_DIR) / settings.GEOAPIFY_RESPONSE_CACHE_DIR
    except Exception:
        return Path("reports/provider-cache/geoapify")


def _safe_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key != "apiKey"}


def _cache_key(url: str, params: dict[str, Any]) -> str:
    raw = json.dumps(
        {"url": url, "params": _safe_params(params)},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return md5(raw.encode()).hexdigest()


def _response_snippet(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text
    else:
        payload = _safe_params(payload) if isinstance(payload, dict) else payload
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    text = " ".join(str(text).split())
    return text[:_MAX_ERROR_SNIPPET_CHARS]


def _read_cached_response(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    if not _cache_enabled():
        return None
    path = _cache_dir() / f"{_cache_key(url, params)}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read Geoapify cache %s: %s", path, exc)
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _write_cached_response(url: str, params: dict[str, Any], data: dict[str, Any]) -> None:
    if not _cache_enabled():
        return
    path = _cache_dir() / f"{_cache_key(url, params)}.json"
    payload = {
        "provider": "geoapify",
        "url": url,
        "params": _safe_params(params),
        "data": data,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    except OSError as exc:
        logger.warning("Failed to write Geoapify cache %s: %s", path, exc)


async def _fetch_geoapify_json(url: str, params: dict[str, Any], timeout: float) -> tuple[dict[str, Any], str]:
    cached = _read_cached_response(url, params)
    if cached is not None:
        return cached, "cache"
    if not _live_enabled():
        logger.info("Geoapify live call skipped because GEOAPIFY_LIVE_ENABLED=false")
        return {}, "live_disabled"

    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        resp = await client.get(url, params=params)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GeoapifyHTTPError(
                status_code=exc.response.status_code,
                response_snippet=_response_snippet(exc.response),
            ) from exc
        data = resp.json()
    _write_cached_response(url, params, data)
    return data, "live"


def _detect_lang(text: str) -> str:
    return "zh" if re.search(r"[\u4e00-\u9fff]", text or "") else "en"


def _iter_geocode_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    results = data.get("results")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]

    features = data.get("features")
    if not isinstance(features, list):
        return []
    normalized: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if len(coords) >= 2:
            properties = dict(properties)
            properties.setdefault("lon", coords[0])
            properties.setdefault("lat", coords[1])
        normalized.append(properties)
    return normalized


def _iter_place_features(data: dict[str, Any]) -> list[dict[str, Any]]:
    features = data.get("features")
    if not isinstance(features, list):
        return []
    normalized: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = dict(feature.get("properties") or {})
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if len(coords) >= 2:
            properties.setdefault("lon", coords[0])
            properties.setdefault("lat", coords[1])
        normalized.append(properties)
    return normalized


def _title(item: dict[str, Any]) -> str:
    return str(
        item.get("name")
        or item.get("address_line1")
        or item.get("formatted")
        or item.get("city")
        or ""
    ).strip()


def _score(item: dict[str, Any]) -> float:
    rank = item.get("rank") if isinstance(item.get("rank"), dict) else {}
    for key in ("confidence", "popularity", "importance"):
        value = rank.get(key)
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
    return 0.6


def _categories(item: dict[str, Any]) -> list[str]:
    categories = item.get("categories")
    if isinstance(categories, list):
        return [str(category) for category in categories[:8]]
    result_type = item.get("result_type")
    return [str(result_type)] if result_type else ["poi"]


def _candidate_from_item(item: dict[str, Any], *, source: str, location_hint: str) -> ProviderCandidate | None:
    title = _title(item)
    if not title:
        return None
    return ProviderCandidate(
        candidate_id=_candidate_id(title, location_hint),
        source=source,
        title=title,
        snippet=str(item.get("formatted") or item.get("address_line2") or ""),
        score=_score(item),
        tags=_categories(item),
        extra={
            "address": item.get("formatted") or item.get("address_line2") or "",
            "city": item.get("city") or "",
            "country": item.get("country") or "",
            "lat": item.get("lat"),
            "lng": item.get("lon"),
            "place_id": item.get("place_id") or "",
            "result_type": item.get("result_type") or "",
            "categories": item.get("categories") or [],
            "datasource": item.get("datasource") or {},
        },
    )


def _dedupe(candidates: list[ProviderCandidate]) -> list[ProviderCandidate]:
    seen: set[str] = set()
    deduped: list[ProviderCandidate] = []
    for candidate in candidates:
        key = f"{candidate.title}|{candidate.extra.get('lat')}|{candidate.extra.get('lng')}".lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


class GeoapifySearchProvider(SearchProvider):
    """Global geocoding search via Geoapify."""

    def __init__(self, api_key: str, *, timeout: float = 10.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "geoapify_search"

    async def search(
        self,
        *,
        query: str,
        top_k: int = 10,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        params: dict[str, Any] = {
            "text": query,
            "format": "json",
            "limit": min(top_k, 20),
            "lang": _detect_lang(query),
            "apiKey": self._api_key,
        }
        data, cache_source = await _fetch_geoapify_json(_GEOCODE_URL, params, self._timeout)

        candidates = [
            candidate
            for item in _iter_geocode_results(data)
            if (candidate := _candidate_from_item(item, source=self.name, location_hint=query)) is not None
        ]
        return ProviderResponse(
            candidates=_dedupe(candidates)[:top_k],
            meta={"cache_source": cache_source, "provider_cost_tier": "low_cost"},
        )


class GeoapifyMapProvider(MapProvider):
    """Global POI lookup via Geoapify geocoding plus Places fallback."""

    def __init__(self, api_key: str, *, timeout: float = 10.0, radius_meters: int = 50000) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._radius_meters = radius_meters

    @property
    def name(self) -> str:
        return "geoapify_map"

    async def nearby_poi(
        self,
        *,
        city: str,
        keywords: list[str],
        top_k: int = 20,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        keyword_text = " ".join(keyword.strip() for keyword in keywords if keyword.strip())
        query = f"{keyword_text}, {city}".strip(" ,") if keyword_text else f"tourist attractions, {city}".strip(" ,")

        geocode_params: dict[str, Any] = {
            "text": query,
            "format": "json",
            "limit": min(top_k, 20),
            "lang": _detect_lang(query),
            "apiKey": self._api_key,
        }
        geocode_data, geocode_cache_source = await _fetch_geoapify_json(
            _GEOCODE_URL,
            geocode_params,
            self._timeout,
        )
        candidates = [
            candidate
            for item in _iter_geocode_results(geocode_data)
            if (candidate := _candidate_from_item(item, source=self.name, location_hint=query)) is not None
        ]

        places_cache_source = ""
        if len(candidates) < top_k and city:
            city_candidate = await self._city_center(city)
            if city_candidate:
                places_candidates, places_cache_source = await self._places_near_city(
                    city=city,
                    keyword_text=keyword_text,
                    center=city_candidate,
                    top_k=top_k - len(candidates),
                )
                candidates.extend(places_candidates)

        cache_sources = [source for source in (geocode_cache_source, places_cache_source) if source]
        return ProviderResponse(
            candidates=_dedupe(candidates)[:top_k],
            degraded=not candidates,
            meta={
                "cache_source": "+".join(cache_sources) if cache_sources else geocode_cache_source,
                "provider_cost_tier": "low_cost",
            },
        )

    async def _city_center(self, city: str) -> dict[str, Any] | None:
        params: dict[str, Any] = {
            "text": city,
            "format": "json",
            "limit": 1,
            "lang": _detect_lang(city),
            "apiKey": self._api_key,
        }
        data, _ = await _fetch_geoapify_json(_GEOCODE_URL, params, self._timeout)
        results = _iter_geocode_results(data)
        return results[0] if results else None

    async def _places_near_city(
        self,
        *,
        city: str,
        keyword_text: str,
        center: dict[str, Any],
        top_k: int,
    ) -> tuple[list[ProviderCandidate], str]:
        lat = center.get("lat")
        lon = center.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return [], ""

        params: dict[str, Any] = {
            "categories": _DEFAULT_PLACE_CATEGORIES,
            "filter": f"circle:{lon},{lat},{self._radius_meters}",
            "bias": f"proximity:{lon},{lat}",
            "limit": min(max(top_k, 1), 20),
            "lang": _detect_lang(f"{keyword_text} {city}"),
            "apiKey": self._api_key,
        }
        if keyword_text:
            params["name"] = keyword_text[:80]

        data, cache_source = await _fetch_geoapify_json(_PLACES_URL, params, self._timeout)
        candidates = [
            candidate
            for item in _iter_place_features(data)
            if (candidate := _candidate_from_item(item, source=self.name, location_hint=city)) is not None
        ]
        return candidates, cache_source
