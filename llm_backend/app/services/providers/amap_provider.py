"""Provider backed by 高德地图 Web服务 API.

Uses two endpoints:
- 关键字搜索: ``/v3/place/text`` — search POIs by keywords + city
- 周边搜索:   ``/v3/place/around`` — search POIs near a coordinate

Docs: https://lbs.amap.com/api/webservice/guide/api/search

Requires ``AMAP_API_KEY`` in .env (Web服务 type key).
Free tier: 5000 calls/day for individual developers.
"""

from __future__ import annotations

import logging
import re
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

_BASE = "https://restapi.amap.com/v3/place"

_TRAVEL_TYPES = "|".join([
    "110000",  # 风景名胜
    "110100",  # 公园广场
    "110200",  # 动植物园
    "110201",  # 植物园
    "110202",  # 动物园
    "110203",  # 水族馆
    "110204",  # 海洋馆
    "110300",  # 游乐园
    "110400",  # 博物馆
    "110000",  # 旅游景点
])

_MAX_KEYWORDS_LEN = 96
_MAX_CITY_LEN = 24


def _sanitize_keywords(raw: str, *, max_len: int = _MAX_KEYWORDS_LEN) -> str:
    """Best-effort keyword sanitization to avoid AMap INVALID_PARAMS."""
    text = (raw or "").strip()
    if not text:
        return ""
    # Keep the first segment before our recall separator to avoid over-long noisy payload.
    text = text.split("|", 1)[0]
    text = re.sub(r"[|:：;；]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


def _sanitize_city(raw: str) -> str:
    city = re.sub(r"\s+", " ", (raw or "").strip())
    if not city:
        return ""
    # Exclude obviously invalid city values with long noise or separators.
    if len(city) > _MAX_CITY_LEN:
        return ""
    if re.search(r"[|:：]", city):
        return ""
    return city


def _parse_poi(poi: dict[str, Any], source: str) -> ProviderCandidate:
    """Convert an Amap POI JSON object to ProviderCandidate."""
    title = poi.get("name", "")
    poi_id = poi.get("id", title)
    location = poi.get("location", "")
    lat, lng = None, None
    if location and "," in location:
        try:
            parts = location.split(",")
            lng_raw, lat_raw = float(parts[0]), float(parts[1])
            # 基本地理范围校验（中国境内坐标）
            if -180 <= lng_raw <= 180 and -90 <= lat_raw <= 90:
                lng, lat = lng_raw, lat_raw
            else:
                logger.warning("Out-of-range coordinates for POI '%s': lng=%s lat=%s", title, lng_raw, lat_raw)
        except (ValueError, IndexError):
            logger.warning("Failed to parse location string '%s' for POI '%s'", location, title)

    rating_str = poi.get("biz_ext", {}).get("rating") or poi.get("biz_ext", {}).get("overall_rating", "")
    rating = 0.0
    if rating_str and rating_str not in ("[]", ""):
        try:
            rating = float(rating_str)
        except (ValueError, TypeError):
            pass

    cost_str = poi.get("biz_ext", {}).get("cost", "")
    cost = 0.0
    if cost_str and cost_str not in ("[]", ""):
        try:
            cost = float(cost_str)
        except (ValueError, TypeError):
            pass

    type_name = poi.get("type", "")
    tags = [t.strip() for t in type_name.split(";") if t.strip()]

    return ProviderCandidate(
        candidate_id=f"amap-{poi_id}",
        source=source,
        title=title,
        snippet=f"{poi.get('address', '')} | {type_name}",
        score=rating / 5.0 if rating > 0 else 0.5,
        tags=tags,
        extra={
            "address": poi.get("address", ""),
            "city": poi.get("cityname", ""),
            "district": poi.get("adname", ""),
            "type": type_name,
            "tel": poi.get("tel", ""),
            "rating": rating,
            "cost_estimate": cost,
            "lat": lat,
            "lng": lng,
            "amap_id": poi_id,
            "photos": [
                p.get("url", "") for p in (poi.get("photos") or [])[:3]
            ],
        },
    )


class AmapSearchProvider(SearchProvider):
    """POI keyword search via 高德 /v3/place/text."""

    def __init__(self, api_key: str, *, timeout: float = 10.0) -> None:
        self._key = api_key
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "amap_search"

    async def search(
        self,
        *,
        query: str,
        top_k: int = 10,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        keywords = _sanitize_keywords(query)
        if not keywords:
            return ProviderResponse(degraded=True)
        params: dict[str, Any] = {
            "key": self._key,
            "keywords": keywords,
            "types": _TRAVEL_TYPES,
            "city": "",
            "citylimit": "false",
            "offset": min(top_k, 25),
            "page": 1,
            "extensions": "all",
            "output": "json",
        }

        city = _sanitize_city(self._extract_city(query))
        if city:
            params["city"] = city
            params["citylimit"] = "true"

        # Ignore host-level proxy env vars to avoid accidental blackhole proxies.
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            resp = await client.get(f"{_BASE}/text", params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "1":
            logger.warning(
                "Amap search error: info=%s infocode=%s city=%s keywords=%s",
                data.get("info", "unknown"),
                data.get("infocode", ""),
                city,
                keywords[:40],
            )
            return ProviderResponse(degraded=True)

        pois = data.get("pois", [])
        candidates = [_parse_poi(p, self.name) for p in pois[:top_k]]
        return ProviderResponse(candidates=candidates)

    @staticmethod
    def _extract_city(query: str) -> str:
        """Try to extract a city name from the query string."""
        # Prefer explicit constrained destination from recall_query.
        explicit = re.search(r"目的地\s*[:：]\s*([^\|\s]+)", query)
        if explicit:
            return explicit.group(1).strip()

        for token in query.replace(",", " ").replace("，", " ").split():
            if len(token) >= 2 and any(
                token.endswith(s) for s in ("市", "省", "区", "县")
            ):
                return token
        # Conservative fallback: only accept short pure CJK/ASCII alphabetic tokens.
        for token in query.replace(",", " ").replace("，", " ").split():
            if len(token) >= 2 and len(token) <= _MAX_CITY_LEN and re.fullmatch(r"[A-Za-z\u4e00-\u9fff]+", token):
                return token
        return ""


class AmapMapProvider(MapProvider):
    """POI keyword search scoped to a city via 高德 /v3/place/text.

    Uses keyword + city filtering rather than coordinate-based
    ``/v3/place/around`` so we don't need to maintain a city→coordinate
    lookup table.
    """

    def __init__(self, api_key: str, *, timeout: float = 10.0) -> None:
        self._key = api_key
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "amap_map"

    async def nearby_poi(
        self,
        *,
        city: str,
        keywords: list[str],
        top_k: int = 20,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        sanitized_keywords = [_sanitize_keywords(k, max_len=48) for k in keywords]
        sanitized_keywords = [k for k in sanitized_keywords if k]
        kw = "|".join(sanitized_keywords[:4]) if sanitized_keywords else "景点"
        city = _sanitize_city(city)
        params: dict[str, Any] = {
            "key": self._key,
            "keywords": kw,
            "types": _TRAVEL_TYPES,
            "city": city,
            "citylimit": "true",
            "offset": min(top_k, 25),
            "page": 1,
            "extensions": "all",
            "output": "json",
        }

        # Ignore host-level proxy env vars to avoid accidental blackhole proxies.
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            resp = await client.get(f"{_BASE}/text", params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "1":
            logger.warning(
                "Amap map error: info=%s infocode=%s city=%s keywords=%s",
                data.get("info", "unknown"),
                data.get("infocode", ""),
                city,
                kw[:40],
            )
            return ProviderResponse(degraded=True)

        pois = data.get("pois", [])
        if not pois:
            return ProviderResponse(degraded=True)

        candidates = [_parse_poi(p, self.name) for p in pois[:top_k]]
        return ProviderResponse(candidates=candidates)
