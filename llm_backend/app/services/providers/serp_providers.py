"""Real providers backed by SerpAPI (Google Search + Google Maps).

Requires a valid ``SERPAPI_KEY`` in .env.
When the key is missing/invalid or a request fails, the caller
(``ProviderOrchestrator``) will catch the error and degrade gracefully.

SerpAPI docs: https://serpapi.com/search-api
Google Maps engine: https://serpapi.com/google-maps-api
"""

from __future__ import annotations

import logging
from hashlib import md5
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

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(_SERPAPI_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()

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

        return ProviderResponse(candidates=candidates)

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

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(_SERPAPI_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()

        candidates: list[ProviderCandidate] = []

        for item in data.get("local_results", [])[:top_k]:
            title = item.get("title", "")
            rating = item.get("rating", 0.0)
            coords = item.get("gps_coordinates", {})

            candidates.append(
                ProviderCandidate(
                    candidate_id=_candidate_id(title, city),
                    source=self.name,
                    title=title,
                    snippet=item.get("description", item.get("type", "")),
                    score=float(rating) / 5.0 if rating else 0.5,
                    tags=self._type_to_tags(item.get("type", "")),
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

        if not candidates:
            return ProviderResponse(degraded=True)

        return ProviderResponse(candidates=candidates)

    @staticmethod
    def _type_to_tags(type_str: str) -> list[str]:
        tags: list[str] = []
        t = type_str.lower()
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
