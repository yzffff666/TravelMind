"""Real providers backed by SerpAPI (Google Search + Google Maps).

Requires a valid ``SERPAPI_KEY`` in .env.
When the key is missing/invalid or a request fails, the caller
(``ProviderOrchestrator``) will catch the error and degrade gracefully.

SerpAPI docs: https://serpapi.com/search-api
Google Maps engine: https://serpapi.com/google-maps-api
"""

from __future__ import annotations

import json
import logging
from hashlib import md5
from pathlib import Path
from typing import Any

import httpx

from app.services.providers.base import (
    MapProvider,
    ProviderCallContext,
    ProviderCandidate,
    ProviderError,
    ProviderErrorCode,
    ProviderResponse,
    SearchProvider,
)

logger = logging.getLogger(__name__)

_SERPAPI_BASE = "https://serpapi.com/search"


def _candidate_id(title: str, city: str) -> str:
    """Deterministic ID so dedup works across providers."""
    raw = f"{title}-{city}".strip().lower()
    return md5(raw.encode()).hexdigest()[:12]


def _cache_enabled() -> bool:
    try:
        from app.core.config import settings
        return bool(settings.SERPAPI_RESPONSE_CACHE_ENABLED)
    except Exception:
        return True


def _cache_dir() -> Path:
    try:
        from app.core.config import ROOT_DIR, settings
        return Path(ROOT_DIR) / settings.SERPAPI_RESPONSE_CACHE_DIR
    except Exception:
        return Path("reports/provider-cache/serpapi")


def _safe_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key != "api_key"}


def _cache_key(params: dict[str, Any]) -> str:
    raw = json.dumps(_safe_params(params), ensure_ascii=False, sort_keys=True, default=str)
    return md5(raw.encode()).hexdigest()


def _read_cached_response(params: dict[str, Any]) -> dict[str, Any] | None:
    if not _cache_enabled():
        return None
    path = _cache_dir() / f"{_cache_key(params)}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read SerpAPI cache %s: %s", path, exc)
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _write_cached_response(params: dict[str, Any], data: dict[str, Any]) -> None:
    if not _cache_enabled():
        return
    path = _cache_dir() / f"{_cache_key(params)}.json"
    payload = {
        "provider": "serpapi",
        "params": _safe_params(params),
        "data": data,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    except OSError as exc:
        logger.warning("Failed to write SerpAPI cache %s: %s", path, exc)


async def _fetch_serpapi_json(params: dict[str, Any], timeout: float) -> tuple[dict[str, Any], str]:
    cached = _read_cached_response(params)
    if cached is not None:
        return cached, "cache"

    # Ignore host-level proxy env vars to avoid accidental blackhole proxies.
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        resp = await client.get(_SERPAPI_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()
    _write_cached_response(params, data)
    return data, "live"


class SerpApiSearchProvider(SearchProvider):
    """Web search via SerpAPI's Google engine.

    Returns travel-related web results (guides, reviews, blogs)
    as ``ProviderCandidate`` objects.
    """

    def __init__(self, api_key: str, *, timeout: float = 12.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "serp_search"

    async def search(
        self,
        *,
        query: str,
        top_k: int = 10,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        params: dict[str, Any] = {
            "engine": "google",
            "q": f"{query} 旅游攻略 景点推荐",
            "api_key": self._api_key,
            "num": min(top_k, 20),
            "hl": "zh-CN",
            "gl": "cn",
        }

        data, cache_source = await _fetch_serpapi_json(params, self._timeout)

        candidates: list[ProviderCandidate] = []

        for item in data.get("organic_results", [])[:top_k]:
            title = item.get("title", "")
            candidates.append(
                ProviderCandidate(
                    candidate_id=_candidate_id(title, query),
                    source=self.name,
                    title=title,
                    snippet=item.get("snippet", ""),
                    score=self._position_score(item.get("position", 99)),
                    tags=self._extract_tags(item),
                    extra={
                        "url": item.get("link", ""),
                        "displayed_link": item.get("displayed_link", ""),
                        "date": item.get("date", ""),
                    },
                )
            )

        return ProviderResponse(candidates=candidates, meta={"cache_source": cache_source})

    @staticmethod
    def _position_score(position: int) -> float:
        """Higher rank → higher score (1.0 for position 1, decays)."""
        return max(0.0, 1.0 - (position - 1) * 0.08)

    @staticmethod
    def _extract_tags(item: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        snippet = (item.get("snippet", "") + item.get("title", "")).lower()
        for kw, tag in [
            ("攻略", "攻略"), ("美食", "美食"), ("景点", "景点"),
            ("酒店", "住宿"), ("交通", "交通"), ("预算", "预算"),
            ("亲子", "亲子"), ("文化", "文化"), ("自然", "自然"),
        ]:
            if kw in snippet:
                tags.append(tag)
        return tags or ["旅游"]


class SerpApiMapProvider(MapProvider):
    """POI search via SerpAPI's Google Maps engine.

    Returns real places (restaurants, attractions, hotels) with
    ratings, addresses, and coordinates.
    """

    def __init__(self, api_key: str, *, timeout: float = 12.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "serp_map"

    async def nearby_poi(
        self,
        *,
        city: str,
        keywords: list[str],
        top_k: int = 20,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        kw_str = " ".join(keywords) if keywords else "景点"
        params: dict[str, Any] = {
            "engine": "google_maps",
            "q": f"{city} {kw_str}",
            "api_key": self._api_key,
            "hl": "zh-CN",
            "ll": "",  # let Google infer from city name
        }

        data, cache_source = await _fetch_serpapi_json(params, self._timeout)

        candidates: list[ProviderCandidate] = []

        for item in data.get("local_results", [])[:top_k]:
            title = item.get("title", "")
            rating = item.get("rating", 0.0)
            coords = item.get("gps_coordinates", {})
            type_value = item.get("type", "")

            candidates.append(
                ProviderCandidate(
                    candidate_id=_candidate_id(title, city),
                    source=self.name,
                    title=title,
                    snippet=item.get("description", self._type_text(type_value)),
                    score=float(rating) / 5.0 if rating else 0.5,
                    tags=self._type_to_tags(type_value),
                    extra={
                        "address": item.get("address", ""),
                        "rating": rating,
                        "reviews_count": item.get("reviews", 0),
                        "phone": item.get("phone", ""),
                        "website": item.get("website", ""),
                        "thumbnail": item.get("thumbnail", ""),
                        "lat": coords.get("latitude"),
                        "lng": coords.get("longitude"),
                        "place_id": item.get("place_id", ""),
                        "hours": item.get("hours", ""),
                        "price": item.get("price", ""),
                    },
                )
            )

        # Exact POI queries often return a single place_results object instead
        # of local_results; treat it as a valid map candidate.
        place = data.get("place_results")
        if not candidates and isinstance(place, dict):
            title = place.get("title", "")
            coords = place.get("gps_coordinates", {})
            if title and coords:
                rating = place.get("rating", 0.0)
                type_value = place.get("type", "")
                candidates.append(
                    ProviderCandidate(
                        candidate_id=_candidate_id(title, city),
                        source=self.name,
                        title=title,
                        snippet=place.get("description", self._type_text(type_value)),
                        score=float(rating) / 5.0 if rating else 0.5,
                        tags=self._type_to_tags(type_value),
                        extra={
                            "address": place.get("address", ""),
                            "rating": rating,
                            "reviews_count": place.get("reviews", 0),
                            "phone": place.get("phone", ""),
                            "website": place.get("website", ""),
                            "thumbnail": place.get("thumbnail") or place.get("serpapi_thumbnail", ""),
                            "lat": coords.get("latitude"),
                            "lng": coords.get("longitude"),
                            "place_id": place.get("place_id", ""),
                            "hours": place.get("hours", ""),
                            "price": place.get("price", ""),
                        },
                    )
                )

        if not candidates:
            return ProviderResponse(degraded=True, meta={"cache_source": cache_source})

        return ProviderResponse(candidates=candidates, meta={"cache_source": cache_source})

    @staticmethod
    def _type_text(type_value: object) -> str:
        if isinstance(type_value, list):
            return " ".join(str(item) for item in type_value)
        return str(type_value or "")

    @classmethod
    def _type_to_tags(cls, type_value: object) -> list[str]:
        tags: list[str] = []
        t = cls._type_text(type_value).lower()
        for kw, tag in [
            ("restaurant", "美食"), ("餐", "美食"), ("cafe", "咖啡"),
            ("hotel", "住宿"), ("酒店", "住宿"), ("hostel", "住宿"),
            ("museum", "博物馆"), ("博物", "博物馆"),
            ("park", "公园"), ("公园", "公园"),
            ("temple", "寺庙"), ("寺", "寺庙"),
            ("mall", "购物"), ("商", "购物"),
            ("scenic", "景点"), ("景", "景点"), ("tourist", "景点"),
        ]:
            if kw in t:
                tags.append(tag)
        return tags or ["景点"]
