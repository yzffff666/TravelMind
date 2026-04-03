"""Mock providers that return fixture data for offline development and testing.

These providers implement the abstract interfaces from ``base.py`` and are
registered via ``ProviderRegistry`` when real API keys are unavailable
or when ``ProviderCallPolicy.fallback_to_mock`` is enabled.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.providers.base import (
    MapProvider,
    ProviderCallContext,
    ProviderCandidate,
    ProviderResponse,
    SearchProvider,
)

_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "mock_poi_data.json"

_CITY_DATA: dict[str, Any] | None = None


def _load_fixture() -> dict[str, Any]:
    global _CITY_DATA  # noqa: PLW0603
    if _CITY_DATA is None:
        with open(_FIXTURE_PATH, encoding="utf-8") as f:
            _CITY_DATA = json.load(f)
    return _CITY_DATA


def _to_candidate(raw: dict[str, Any], source: str) -> ProviderCandidate:
    return ProviderCandidate(
        candidate_id=raw["candidate_id"],
        source=source,
        title=raw["title"],
        snippet=raw.get("snippet", ""),
        score=raw.get("score", 0.0),
        tags=raw.get("tags", []),
        extra=raw.get("extra", {}),
    )


def _match_query(candidate: dict[str, Any], query: str) -> bool:
    """Loose keyword match against title, snippet, and tags."""
    q = query.lower()
    text = (
        candidate.get("title", "")
        + candidate.get("snippet", "")
        + " ".join(candidate.get("tags", []))
    ).lower()
    return any(kw in text for kw in q.split()) or q in text


def _find_city(query: str) -> str | None:
    data = _load_fixture()
    for city in data:
        if city in query:
            return city
    return None


class MockSearchProvider(SearchProvider):
    """Returns fixture search results for known cities."""

    @property
    def name(self) -> str:
        return "mock_search"

    async def search(
        self,
        *,
        query: str,
        top_k: int = 10,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        data = _load_fixture()
        city = _find_city(query)
        if not city:
            return ProviderResponse(degraded=True)

        raw_list: list[dict[str, Any]] = data[city].get("search", [])
        matched = [r for r in raw_list if _match_query(r, query)]
        if not matched:
            matched = raw_list

        candidates = [_to_candidate(r, self.name) for r in matched[:top_k]]
        return ProviderResponse(candidates=candidates)


class MockMapProvider(MapProvider):
    """Returns fixture map/POI results for known cities."""

    @property
    def name(self) -> str:
        return "mock_map"

    async def nearby_poi(
        self,
        *,
        city: str,
        keywords: list[str],
        top_k: int = 20,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        data = _load_fixture()
        target_city: str | None = None
        for c in data:
            if c in city or city in c:
                target_city = c
                break

        if not target_city:
            return ProviderResponse(degraded=True)

        raw_list: list[dict[str, Any]] = data[target_city].get("map", [])
        candidates = [_to_candidate(r, self.name) for r in raw_list[:top_k]]
        return ProviderResponse(candidates=candidates)
