"""Dynamic destination grounding for travel-planning candidates.

Static city bounds are useful fast paths for common destinations, but they
cannot safely cover arbitrary cities.  This module resolves a destination into
a reusable profile and uses that profile to reject cross-city candidates before
they reach ranking or the LLM prompt.
"""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.services.geo_bounds import destination_bounds
from app.services.providers.base import ProviderCandidate
from app.services.providers.geoapify_provider import GeoapifySearchProvider


_AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
_GEOAPIFY_LOCALITY_FIELDS = (
    "suburb",
    "district",
    "city",
    "municipality",
    "county",
    "state",
)
_LOCALITY_SPECIFICITY = {
    "suburb": 6,
    "district": 5,
    "city": 4,
    "municipality": 4,
    "county": 3,
    "state": 1,
}
_LATIN_TRANSLITERATION = str.maketrans(
    {
        "ø": "o",
        "Ø": "O",
        "æ": "ae",
        "Æ": "AE",
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "ð": "d",
        "Ð": "D",
        "þ": "th",
        "Þ": "Th",
    }
)


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def has_valid_coordinates(candidate: ProviderCandidate) -> bool:
    """Whether a provider candidate has a usable geographic point.

    ``static_legacy_no_geo`` remains supported by the low-level destination
    validator for backwards compatibility, but callers that publish an
    itinerary must require this stricter check.
    """
    lat = _as_float(candidate.extra.get("lat"))
    lng = _as_float(candidate.extra.get("lng"))
    return bool(
        lat is not None
        and lng is not None
        and -90 <= lat <= 90
        and -180 <= lng <= 180
    )


def _normalize_text(value: object) -> str:
    text = str(value or "").translate(_LATIN_TRANSLITERATION)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    earth_radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return earth_radius * 2 * atan2(sqrt(a), sqrt(1 - a))


@dataclass(slots=True)
class DestinationProfile:
    requested_name: str
    canonical_name: str = ""
    country: str = ""
    admin_area: str = ""
    center_lat: float | None = None
    center_lng: float | None = None
    bounds: tuple[float, float, float, float] | None = None
    radius_km: float = 40.0
    confidence: float = 0.0
    source: str = "none"
    is_dynamic: bool = True
    cache_hit: bool = False

    @property
    def resolved(self) -> bool:
        return bool(
            self.canonical_name
            and self.center_lat is not None
            and self.center_lng is not None
            and self.confidence >= 0.5
        )

    def match_terms(self) -> set[str]:
        return {
            value
            for value in {
                _normalize_text(self.requested_name),
                _normalize_text(self.canonical_name),
                _normalize_text(self.admin_area),
            }
            if len(value) >= 2
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_name": self.requested_name,
            "canonical_name": self.canonical_name,
            "country": self.country,
            "admin_area": self.admin_area,
            "center_lat": self.center_lat,
            "center_lng": self.center_lng,
            "bounds": list(self.bounds) if self.bounds else None,
            "radius_km": self.radius_km,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "is_dynamic": self.is_dynamic,
            "cache_hit": self.cache_hit,
            "resolved": self.resolved,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "DestinationProfile":
        payload = payload or {}
        raw_bounds = payload.get("bounds")
        bounds: tuple[float, float, float, float] | None = None
        if isinstance(raw_bounds, (list, tuple)) and len(raw_bounds) == 4:
            values = tuple(_as_float(value) for value in raw_bounds)
            if all(value is not None for value in values):
                bounds = values  # type: ignore[assignment]
        return cls(
            requested_name=str(payload.get("requested_name") or ""),
            canonical_name=str(payload.get("canonical_name") or ""),
            country=str(payload.get("country") or ""),
            admin_area=str(payload.get("admin_area") or ""),
            center_lat=_as_float(payload.get("center_lat")),
            center_lng=_as_float(payload.get("center_lng")),
            bounds=bounds,
            radius_km=float(payload.get("radius_km") or 40.0),
            confidence=float(payload.get("confidence") or 0.0),
            source=str(payload.get("source") or "none"),
            is_dynamic=bool(payload.get("is_dynamic", True)),
            cache_hit=bool(payload.get("cache_hit", False)),
        )


@dataclass(slots=True)
class CandidateGroundingDecision:
    accepted: bool
    reason: str
    distance_km: float | None = None
    city_match: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "distance_km": round(self.distance_km, 3) if self.distance_km is not None else None,
            "city_match": self.city_match,
        }


class DestinationLookup(Protocol):
    name: str

    async def lookup(self, destination: str) -> DestinationProfile | None:
        ...


class AmapDestinationLookup:
    """Chinese destination geocoder backed by Amap's address API."""

    name = "amap_geocode"

    def __init__(self, api_key: str, *, timeout_seconds: float = 3.0, radius_km: float = 40.0) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._radius_km = radius_km

    async def lookup(self, destination: str) -> DestinationProfile | None:
        params = {
            "key": self._api_key,
            "address": destination,
            "output": "json",
        }
        async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
            response = await client.get(_AMAP_GEOCODE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") != "1":
            return None
        geocodes = payload.get("geocodes") or []
        if not geocodes or not isinstance(geocodes[0], dict):
            return None
        return _amap_destination_profile(
            destination,
            geocodes[0],
            radius_km=self._radius_km,
            source=self.name,
        )


class GeoapifyDestinationLookup:
    """Global destination geocoder reusing Geoapify's cached search adapter."""

    name = "geoapify_geocode"

    def __init__(self, api_key: str, *, timeout_seconds: float = 3.0, radius_km: float = 40.0) -> None:
        self._provider = GeoapifySearchProvider(api_key, timeout=timeout_seconds)
        self._radius_km = radius_km

    async def lookup(self, destination: str) -> DestinationProfile | None:
        responses = await asyncio.gather(
            self._provider.search(query=destination, top_k=5),
            self._provider.search_city(city=destination, top_k=5),
            return_exceptions=True,
        )
        best: ProviderCandidate | None = None
        best_score = -1.0
        candidates = [
            candidate
            for response in responses
            if not isinstance(response, BaseException)
            for candidate in response.candidates
        ]
        for candidate in candidates:
            lat = _as_float(candidate.extra.get("lat"))
            lng = _as_float(candidate.extra.get("lng"))
            if lat is None or lng is None:
                continue
            canonical, _canonical_field = _matching_geoapify_locality(
                destination,
                candidate,
            )
            canonical = canonical or str(
                candidate.extra.get("city") or candidate.title or ""
            ).strip()
            score = candidate.score + (0.25 if _destination_name_matches(destination, canonical) else 0.0)
            result_type = str(candidate.extra.get("result_type") or "").lower()
            if result_type in {"city", "municipality"}:
                score += 0.15
            elif result_type in {"county", "district"}:
                score += 0.05
            rank = candidate.extra.get("rank")
            if isinstance(rank, dict):
                popularity = _as_float(rank.get("popularity")) or 0.0
                importance = _as_float(rank.get("importance")) or 0.0
                score += min(max(popularity, 0.0), 5.0) * 0.03
                score += min(max(importance, 0.0), 1.0) * 0.1
            if score > best_score:
                best = candidate
                best_score = score
        if best is None:
            return None

        canonical, _canonical_field = _matching_geoapify_locality(destination, best)
        canonical = canonical or str(
            best.extra.get("city") or best.title or destination
        ).strip()
        return DestinationProfile(
            requested_name=destination,
            canonical_name=canonical,
            country=str(best.extra.get("country") or "").strip(),
            admin_area=_geoapify_parent_admin(best, canonical),
            center_lat=_as_float(best.extra.get("lat")),
            center_lng=_as_float(best.extra.get("lng")),
            radius_km=self._radius_km,
            confidence=min(0.95, max(0.55, best_score)),
            source=self.name,
            is_dynamic=True,
        )


def _destination_name_matches(requested: str, canonical: str) -> bool:
    return _destination_name_match_quality(requested, canonical) > 0


def _destination_name_match_quality(requested: str, canonical: str) -> int:
    left = _normalize_text(requested)
    right = _normalize_text(canonical)
    if not left or not right:
        return 0
    if left == right:
        return 2
    return 1 if left in right or right in left else 0


def _matching_geoapify_locality(
    destination: str,
    candidate: ProviderCandidate,
) -> tuple[str, str]:
    matches: list[tuple[int, int, str, str]] = []
    for field in _GEOAPIFY_LOCALITY_FIELDS:
        value = str(candidate.extra.get(field) or "").strip()
        quality = _destination_name_match_quality(destination, value)
        if quality:
            matches.append(
                (quality, _LOCALITY_SPECIFICITY[field], value, field)
            )
    non_state_matches = [match for match in matches if match[3] != "state"]
    if non_state_matches:
        _quality, _specificity, value, field = max(non_state_matches)
        return value, field
    if matches:
        _quality, _specificity, value, field = max(matches)
        return value, field
    if _destination_name_matches(destination, candidate.title):
        return candidate.title.strip(), "title"
    return "", ""


def _geoapify_parent_admin(
    candidate: ProviderCandidate,
    canonical: str,
) -> str:
    canonical_normalized = _normalize_text(canonical)
    for field in ("city", "municipality", "county", "state"):
        value = str(candidate.extra.get(field) or "").strip()
        if value and _normalize_text(value) != canonical_normalized:
            return value
    return ""


def _amap_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text in {"[]", "None", "null"} else text


def _amap_destination_profile(
    destination: str,
    item: dict[str, Any],
    *,
    radius_km: float,
    source: str,
) -> DestinationProfile | None:
    """Build a profile without widening a district/town request to its parent city.

    AMap's ``city`` field is often the prefecture-level city. For instance,
    a lookup for ``敦煌`` can return ``city=酒泉市`` and ``district=敦煌市``.
    We preserve the most specific matching administrative label for retrieval
    while keeping the parent city as a valid candidate-city context.
    """
    location = _amap_text(item.get("location"))
    if "," not in location:
        return None
    lng, lat = (_as_float(value) for value in location.split(",", 1))
    if lat is None or lng is None:
        return None

    labels = [
        _amap_text(item.get("township")),
        _amap_text(item.get("district")),
        _amap_text(item.get("city")),
        _amap_text(item.get("province")),
    ]
    matching_label = next(
        (label for label in labels if label and _destination_name_matches(destination, label)),
        "",
    )
    canonical = matching_label or destination
    city = _amap_text(item.get("city"))
    province = _amap_text(item.get("province"))
    admin_area = city if city and _normalize_text(city) != _normalize_text(canonical) else province
    return DestinationProfile(
        requested_name=destination,
        canonical_name=canonical,
        country="中国",
        admin_area=admin_area,
        center_lat=lat,
        center_lng=lng,
        radius_km=radius_km,
        confidence=0.9 if matching_label else 0.7,
        source=source,
        is_dynamic=True,
    )


class DestinationResolver:
    """Resolve destinations with static fast paths and dynamic provider fallbacks."""

    def __init__(
        self,
        *,
        lookups: list[DestinationLookup] | None = None,
        cache_ttl_seconds: float | None = None,
        radius_km: float | None = None,
    ) -> None:
        self._radius_km = float(radius_km or settings.DESTINATION_GROUNDING_RADIUS_KM)
        self._cache_ttl_seconds = float(
            cache_ttl_seconds or settings.DESTINATION_GROUNDING_CACHE_TTL_SECONDS
        )
        self._lookups = lookups if lookups is not None else self._default_lookups()
        self._cache: dict[str, tuple[float, DestinationProfile]] = {}
        self._lock = asyncio.Lock()

    def _default_lookups(self) -> list[DestinationLookup]:
        timeout = float(settings.DESTINATION_GROUNDING_TIMEOUT_SECONDS)
        lookups: list[DestinationLookup] = []
        if settings.AMAP_ENABLED and settings.AMAP_API_KEY.strip():
            lookups.append(
                AmapDestinationLookup(
                    settings.AMAP_API_KEY,
                    timeout_seconds=timeout,
                    radius_km=self._radius_km,
                )
            )
        if settings.GEOAPIFY_ENABLED and settings.GEOAPIFY_KEY.strip():
            lookups.append(
                GeoapifyDestinationLookup(
                    settings.GEOAPIFY_KEY,
                    timeout_seconds=timeout,
                    radius_km=self._radius_km,
                )
            )
        return lookups

    async def resolve(self, destination: str) -> DestinationProfile:
        requested = str(destination or "").strip()
        if not requested:
            return DestinationProfile(requested_name="")

        static = destination_bounds(requested)
        if static is not None:
            min_lat, max_lat, min_lng, max_lng = static
            return DestinationProfile(
                requested_name=requested,
                canonical_name=requested,
                center_lat=(min_lat + max_lat) / 2,
                center_lng=(min_lng + max_lng) / 2,
                bounds=static,
                confidence=1.0,
                source="static_bounds",
                is_dynamic=False,
            )

        key = _normalize_text(requested)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return replace(cached[1], cache_hit=True)

        async with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return replace(cached[1], cache_hit=True)
            profile = await self._resolve_dynamic(requested)
            self._cache[key] = (time.monotonic() + self._cache_ttl_seconds, profile)
            return profile

    async def _resolve_dynamic(self, destination: str) -> DestinationProfile:
        ordered = self._ordered_lookups(destination)
        for lookup in ordered:
            try:
                profile = await lookup.lookup(destination)
            except Exception:  # Provider errors must become safe degradation.
                continue
            if profile and profile.resolved:
                return profile
        return DestinationProfile(requested_name=destination)

    def _ordered_lookups(self, destination: str) -> list[DestinationLookup]:
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", destination))
        return sorted(
            self._lookups,
            key=lambda lookup: 0 if (has_cjk and lookup.name.startswith("amap")) or (
                not has_cjk and lookup.name.startswith("geoapify")
            ) else 1,
        )

    def clear_cache(self) -> None:
        self._cache.clear()


def validate_candidate_destination(
    candidate: ProviderCandidate,
    profile: DestinationProfile,
) -> CandidateGroundingDecision:
    """Validate one candidate against a resolved destination profile.

    Dynamic profiles require coordinates. Static profiles preserve legacy
    behavior for coordinate-less candidates so existing common-city recall does
    not regress while the dynamic path is rolled out.
    """
    if not profile.resolved:
        return CandidateGroundingDecision(False, "destination_unresolved")

    lat = _as_float(candidate.extra.get("lat"))
    lng = _as_float(candidate.extra.get("lng"))
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        if profile.is_dynamic:
            return CandidateGroundingDecision(False, "missing_geo")
        return CandidateGroundingDecision(True, "static_legacy_no_geo")

    if profile.bounds is not None:
        min_lat, max_lat, min_lng, max_lng = profile.bounds
        if not (min_lat <= lat <= max_lat and min_lng <= lng <= max_lng):
            return CandidateGroundingDecision(False, "outside_destination_bounds")
        return CandidateGroundingDecision(True, "within_destination_bounds", distance_km=0.0)

    assert profile.center_lat is not None and profile.center_lng is not None
    distance_km = _haversine_km(profile.center_lat, profile.center_lng, lat, lng)
    if distance_km > profile.radius_km:
        return CandidateGroundingDecision(False, "outside_destination_radius", distance_km=distance_km)

    candidate_city = str(candidate.extra.get("city") or "").strip()
    city_match: bool | None = None
    destination_terms = {
        term
        for term in {
            _normalize_text(profile.requested_name),
            _normalize_text(profile.canonical_name),
        }
        if len(term) >= 2
    }
    parent_term = _normalize_text(profile.admin_area)
    if candidate_city:
        candidate_city_normalized = _normalize_text(candidate_city)
        city_match = any(
            term in candidate_city_normalized or candidate_city_normalized in term
            for term in destination_terms
        )
        if not city_match and len(parent_term) >= 2:
            parent_match = (
                parent_term in candidate_city_normalized
                or candidate_city_normalized in parent_term
            )
            city_match = parent_match
            if parent_match and profile.source.startswith("geoapify"):
                narrow_localities = {
                    normalized
                    for field in ("suburb", "district", "municipality", "county")
                    if (normalized := _normalize_text(candidate.extra.get(field)))
                }
                city_match = any(
                    term in locality or locality in term
                    for term in destination_terms
                    for locality in narrow_localities
                )
        if not city_match:
            return CandidateGroundingDecision(
                False,
                "candidate_city_mismatch",
                distance_km,
                city_match,
            )
    else:
        narrow_localities = {
            normalized
            for field in ("suburb", "district", "municipality", "county")
            if (normalized := _normalize_text(candidate.extra.get(field)))
        }
        if narrow_localities:
            city_match = any(
                term in locality or locality in term
                for term in destination_terms
                for locality in narrow_localities
            )
            if not city_match:
                return CandidateGroundingDecision(
                    False,
                    "candidate_city_mismatch",
                    distance_km,
                    city_match,
                )
    return CandidateGroundingDecision(True, "grounded", distance_km, city_match)


def filter_candidates_for_destination(
    candidates: list[ProviderCandidate],
    profile: DestinationProfile,
) -> tuple[list[ProviderCandidate], list[CandidateGroundingDecision]]:
    accepted: list[ProviderCandidate] = []
    decisions: list[CandidateGroundingDecision] = []
    for candidate in candidates:
        decision = validate_candidate_destination(candidate, profile)
        candidate.extra["destination_grounding"] = decision.to_dict()
        decisions.append(decision)
        if decision.accepted:
            accepted.append(candidate)
    return accepted, decisions
