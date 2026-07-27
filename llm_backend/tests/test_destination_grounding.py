import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.destination_grounding import (
    DestinationProfile,
    DestinationResolver,
    GeoapifyDestinationLookup,
    _amap_destination_profile,
    filter_candidates_for_destination,
    validate_candidate_destination,
)
from app.services.providers.base import ProviderCandidate, ProviderResponse


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


def test_diacritic_equivalent_locality_is_grounded_without_alias_configuration():
    profile = DestinationProfile(
        requested_name="Tromso",
        canonical_name="Tromsø",
        country="Norway",
        admin_area="Troms",
        center_lat=69.6516,
        center_lng=18.9559,
        radius_km=40,
        confidence=0.95,
        source="geoapify_geocode",
        is_dynamic=True,
    )
    candidate = ProviderCandidate(
        candidate_id="arctic-cathedral",
        source="geoapify_map",
        title="Arctic Cathedral",
        extra={
            "lat": 69.648,
            "lng": 18.987,
            "city": "Tromsø",
            "county": "Troms",
            "locality_terms": ["Tromsø", "Troms"],
        },
    )

    decision = validate_candidate_destination(candidate, profile)

    assert decision.accepted is True
    assert decision.reason == "grounded"


def test_parent_locality_match_accepts_suburb_but_contradictory_locality_is_rejected():
    profile = DestinationProfile(
        requested_name="Hobart",
        canonical_name="Hobart",
        country="Australia",
        admin_area="Tasmania",
        center_lat=-42.8825,
        center_lng=147.3281,
        radius_km=40,
        confidence=0.95,
        source="geoapify_geocode",
        is_dynamic=True,
    )
    local_suburb = ProviderCandidate(
        candidate_id="cascade-female-factory",
        source="geoapify_map",
        title="Cascades Female Factory",
        extra={
            "lat": -42.8956,
            "lng": 147.3002,
            "city": "Hobart",
            "suburb": "Battery Point",
            "state": "Tasmania",
            "locality_terms": ["Battery Point", "Hobart", "Tasmania"],
        },
    )
    contradictory = ProviderCandidate(
        candidate_id="launceston-decoy",
        source="geoapify_map",
        title="Wrong City Museum",
        extra={
            "lat": -42.89,
            "lng": 147.31,
            "city": "Launceston",
            "state": "Tasmania",
            "locality_terms": ["Launceston", "Tasmania"],
        },
    )

    assert validate_candidate_destination(local_suburb, profile).accepted is True
    rejected = validate_candidate_destination(contradictory, profile)
    assert rejected.accepted is False
    assert rejected.reason == "candidate_city_mismatch"


@pytest.mark.asyncio
async def test_geoapify_destination_lookup_combines_text_and_structured_results_for_global_names():
    lookup = GeoapifyDestinationLookup("fake-key")
    australian_hobart = ProviderCandidate(
        candidate_id="hobart-au",
        source="geoapify_search",
        title="Hobart",
        score=1.0,
        extra={
            "city": "Hobart",
            "state": "Tasmania",
            "country": "Australia",
            "lat": -42.8825,
            "lng": 147.3281,
            "result_type": "city",
            "rank": {"popularity": 4.0192, "importance": 0.6233},
        },
    )
    american_hobart = ProviderCandidate(
        candidate_id="hobart-us",
        source="geoapify_search",
        title="Hobart",
        score=1.0,
        extra={
            "city": "Hobart",
            "state": "Indiana",
            "country": "United States",
            "lat": 41.5323,
            "lng": -87.255,
            "result_type": "city",
            "rank": {"popularity": 3.3736, "importance": 0.4348},
        },
    )
    lookup._provider.search = AsyncMock(
        return_value=ProviderResponse(candidates=[australian_hobart])
    )
    lookup._provider.search_city = AsyncMock(
        return_value=ProviderResponse(candidates=[american_hobart])
    )

    profile = await lookup.lookup("Hobart")

    assert profile is not None
    assert profile.country == "Australia"
    assert profile.admin_area == "Tasmania"
    assert profile.center_lat == -42.8825
    assert profile.center_lng == 147.3281


def test_same_state_different_city_cannot_override_explicit_city_contradiction():
    profile = DestinationProfile(
        requested_name="Oaxaca",
        canonical_name="Oaxaca City",
        country="Mexico",
        admin_area="Oaxaca",
        center_lat=17.0605,
        center_lng=-96.7254,
        radius_km=40,
        confidence=0.95,
        source="geoapify_geocode",
        is_dynamic=True,
    )
    candidate = ProviderCandidate(
        candidate_id="nearby-wrong-city",
        source="geoapify_map",
        title="Wrong City Attraction",
        extra={
            "lat": 17.028,
            "lng": -96.72,
            "city": "Santa Cruz Xoxocotlán",
            "state": "Oaxaca",
            "country": "Mexico",
            "locality_terms": ["Santa Cruz Xoxocotlán", "Oaxaca", "Mexico"],
        },
    )

    decision = validate_candidate_destination(candidate, profile)

    assert decision.accepted is False
    assert decision.reason == "candidate_city_mismatch"


def test_geoapify_parent_city_requires_matching_narrow_locality():
    profile = DestinationProfile(
        requested_name="Brooklyn",
        canonical_name="Brooklyn",
        country="United States",
        admin_area="New York",
        center_lat=40.6526,
        center_lng=-73.9497,
        radius_km=40,
        confidence=0.95,
        source="geoapify_geocode",
        is_dynamic=True,
    )
    brooklyn = ProviderCandidate(
        candidate_id="brooklyn-museum",
        source="geoapify_map",
        title="Brooklyn Museum",
        extra={
            "lat": 40.6712,
            "lng": -73.9636,
            "city": "New York",
            "suburb": "Brooklyn",
        },
    )
    manhattan = ProviderCandidate(
        candidate_id="manhattan-decoy",
        source="geoapify_map",
        title="Manhattan Attraction",
        extra={
            "lat": 40.7061,
            "lng": -74.0087,
            "city": "New York",
            "suburb": "Manhattan",
        },
    )

    assert validate_candidate_destination(brooklyn, profile).accepted is True
    rejected = validate_candidate_destination(manhattan, profile)
    assert rejected.accepted is False
    assert rejected.reason == "candidate_city_mismatch"


@pytest.mark.asyncio
async def test_geoapify_destination_lookup_preserves_matching_suburb_instead_of_parent_city():
    lookup = GeoapifyDestinationLookup("fake-key")
    brooklyn = ProviderCandidate(
        candidate_id="brooklyn",
        source="geoapify_search",
        title="Brooklyn",
        score=1.0,
        extra={
            "city": "New York",
            "suburb": "Brooklyn",
            "state": "New York",
            "country": "United States",
            "lat": 40.6526,
            "lng": -73.9497,
            "result_type": "suburb",
            "rank": {"popularity": 5.0, "importance": 0.7},
        },
    )
    response = ProviderResponse(candidates=[brooklyn])
    lookup._provider.search = AsyncMock(return_value=response)
    lookup._provider.search_city = AsyncMock(return_value=ProviderResponse())

    profile = await lookup.lookup("Brooklyn")

    assert profile is not None
    assert profile.canonical_name == "Brooklyn"
    assert profile.admin_area == "New York"


@pytest.mark.asyncio
async def test_geoapify_destination_lookup_prefers_diacritic_city_over_similar_county():
    lookup = GeoapifyDestinationLookup("fake-key")
    tromso = ProviderCandidate(
        candidate_id="tromso",
        source="geoapify_search",
        title="Tromsø",
        score=1.0,
        extra={
            "city": "Tromsø",
            "county": "Troms",
            "country": "Norway",
            "lat": 69.6516,
            "lng": 18.9559,
            "result_type": "city",
            "rank": {"popularity": 2.9, "importance": 0.5},
        },
    )
    response = ProviderResponse(candidates=[tromso])
    lookup._provider.search = AsyncMock(return_value=response)
    lookup._provider.search_city = AsyncMock(return_value=ProviderResponse())

    profile = await lookup.lookup("Tromso")

    assert profile is not None
    assert profile.canonical_name == "Tromsø"
    assert profile.admin_area == "Troms"
