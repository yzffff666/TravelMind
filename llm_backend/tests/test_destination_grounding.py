import asyncio

import pytest

from app.services.destination_grounding import (
    DestinationProfile,
    DestinationResolver,
    _amap_destination_profile,
    filter_candidates_for_destination,
    validate_candidate_destination,
)
from app.services.providers.base import ProviderCandidate


UNSEEN_DESTINATIONS = {
    "景德镇": (29.2687, 117.1784, "中国"),
    "延吉": (42.9094, 129.5078, "中国"),
    "敦煌": (40.1421, 94.6619, "中国"),
    "自贡": (29.3392, 104.7784, "中国"),
    "喀什": (39.4704, 75.9898, "中国"),
    "泉州": (24.8744, 118.6757, "中国"),
    "Tromso": (69.6492, 18.9553, "Norway"),
    "Hobart": (-42.8821, 147.3272, "Australia"),
    "Valletta": (35.8989, 14.5146, "Malta"),
    "Oaxaca": (17.0732, -96.7266, "Mexico"),
}


class _FixtureLookup:
    name = "fixture_geocoder"

    def __init__(self):
        self.calls = 0

    async def lookup(self, destination: str):
        self.calls += 1
        entry = UNSEEN_DESTINATIONS.get(destination)
        if entry is None:
            return None
        lat, lng, country = entry
        return DestinationProfile(
            requested_name=destination,
            canonical_name=destination,
            country=country,
            center_lat=lat,
            center_lng=lng,
            radius_km=45,
            confidence=0.91,
            source=self.name,
            is_dynamic=True,
        )


def _candidate(title: str, *, lat: float | None, lng: float | None, city: str = ""):
    extra = {"city": city}
    if lat is not None:
        extra["lat"] = lat
    if lng is not None:
        extra["lng"] = lng
    return ProviderCandidate(
        candidate_id=f"candidate-{title}",
        source="fixture",
        title=title,
        extra=extra,
    )


@pytest.mark.asyncio
async def test_unseen_destinations_resolve_without_static_bounds_and_cache():
    lookup = _FixtureLookup()
    resolver = DestinationResolver(lookups=[lookup], cache_ttl_seconds=60)

    for destination, (lat, lng, country) in UNSEEN_DESTINATIONS.items():
        profile = await resolver.resolve(destination)
        assert profile.resolved
        assert profile.is_dynamic is True
        assert profile.source == "fixture_geocoder"
        assert profile.country == country
        assert profile.center_lat == lat
        assert profile.center_lng == lng
        assert profile.bounds is None

    again = await resolver.resolve("景德镇")
    assert again.cache_hit is True
    assert lookup.calls == len(UNSEEN_DESTINATIONS)


@pytest.mark.asyncio
async def test_unseen_profile_accepts_local_candidates_and_rejects_cross_city_decoys():
    resolver = DestinationResolver(lookups=[_FixtureLookup()])
    profile = await resolver.resolve("敦煌")

    accepted, decisions = filter_candidates_for_destination(
        [
            _candidate("莫高窟", lat=40.1424, lng=94.6615, city="敦煌市"),
            _candidate("鸣沙山月牙泉", lat=40.0885, lng=94.6811, city="敦煌市"),
            _candidate("东京塔", lat=35.6586, lng=139.7454, city="Tokyo"),
            _candidate("错误城市字段", lat=40.1424, lng=94.6615, city="酒泉市"),
        ],
        profile,
    )

    assert [candidate.title for candidate in accepted] == ["莫高窟", "鸣沙山月牙泉"]
    assert [decision.reason for decision in decisions] == [
        "grounded",
        "grounded",
        "outside_destination_radius",
        "candidate_city_mismatch",
    ]


@pytest.mark.asyncio
async def test_dynamic_profile_requires_geo_but_static_profile_keeps_legacy_candidate_compatibility():
    resolver = DestinationResolver(lookups=[_FixtureLookup()])
    dynamic_profile = await resolver.resolve("景德镇")
    static_profile = await resolver.resolve("上海")
    coordinate_less = _candidate("无坐标候选", lat=None, lng=None)

    assert validate_candidate_destination(coordinate_less, dynamic_profile).reason == "missing_geo"
    legacy_decision = validate_candidate_destination(coordinate_less, static_profile)
    assert legacy_decision.accepted is True
    assert legacy_decision.reason == "static_legacy_no_geo"


def test_resolver_returns_unresolved_profile_when_every_lookup_misses():
    resolver = DestinationResolver(lookups=[])
    profile = asyncio.run(resolver.resolve("不存在的测试城市"))

    assert profile.resolved is False
    assert profile.source == "none"


def test_amap_profile_keeps_specific_destination_and_accepts_parent_city_context():
    profile = _amap_destination_profile(
        "敦煌",
        {
            "location": "94.6619,40.1421",
            "province": "甘肃省",
            "city": "酒泉市",
            "district": "敦煌市",
        },
        radius_km=40,
        source="amap_geocode",
    )

    assert profile is not None
    assert profile.canonical_name == "敦煌市"
    assert profile.admin_area == "酒泉市"
    local = _candidate("莫高窟", lat=40.1424, lng=94.6615, city="酒泉市")
    decision = validate_candidate_destination(local, profile)
    assert decision.accepted is True
    assert decision.reason == "grounded"
