from app.services.candidate_publishability import evaluate_candidate_publishability
from app.services.destination_grounding import DestinationProfile
from app.services.providers.base import ProviderCandidate


def _profile(*, dynamic: bool = False) -> DestinationProfile:
    return DestinationProfile(
        requested_name="上海",
        canonical_name="上海",
        center_lat=31.2304,
        center_lng=121.4737,
        bounds=None if dynamic else (30.6, 31.9, 120.8, 122.2),
        radius_km=45.0,
        confidence=0.95,
        source="fixture_geocoder" if dynamic else "static_bounds",
        is_dynamic=dynamic,
    )


def _candidate(
    title: str,
    *,
    lat: float | None = 31.2304,
    lng: float | None = 121.4737,
    source: str = "fixture_map",
    city: str = "上海",
) -> ProviderCandidate:
    extra = {"city": city}
    if lat is not None:
        extra["lat"] = lat
    if lng is not None:
        extra["lng"] = lng
    return ProviderCandidate(
        candidate_id=f"candidate-{title}",
        source=source,
        title=title,
        extra=extra,
    )


def test_publishability_accepts_enough_coordinate_backed_local_candidates():
    candidates = [_candidate(f"上海景点{i}") for i in range(3)]

    result = evaluate_candidate_publishability(
        candidates,
        _profile(),
        required_count=3,
    )

    assert result.ready is True
    assert result.status == "ready"
    assert result.accepted == candidates
    assert result.reject_reason_counts == {}


def test_publishability_rejects_static_candidate_without_coordinates():
    result = evaluate_candidate_publishability(
        [_candidate("无坐标候选", lat=None, lng=None)],
        _profile(),
        required_count=1,
    )

    assert result.ready is False
    assert result.status == "insufficient_candidates"
    assert result.accepted == []
    assert result.reject_reason_counts == {"missing_geo": 1}


def test_publishability_preserves_dynamic_cross_city_reject_reason():
    result = evaluate_candidate_publishability(
        [_candidate("东京塔", lat=35.6586, lng=139.7454, city="Tokyo")],
        _profile(dynamic=True),
        required_count=1,
    )

    assert result.ready is False
    assert result.reject_reason_counts == {"outside_destination_radius": 1}


def test_publishability_rejects_invalid_coordinates():
    result = evaluate_candidate_publishability(
        [_candidate("坏坐标", lat=181.0, lng=121.4737)],
        _profile(),
        required_count=1,
    )

    assert result.ready is False
    assert result.reject_reason_counts == {"missing_geo": 1}


def test_publishability_rejects_mock_candidate_by_default():
    result = evaluate_candidate_publishability(
        [_candidate("Mock 景点", source="mock_map")],
        _profile(),
        required_count=1,
    )

    assert result.ready is False
    assert result.reject_reason_counts == {"mock_candidate": 1}


def test_publishability_can_allow_mock_candidate_for_explicit_test_mode():
    candidate = _candidate("Mock 景点", source="mock_map")

    result = evaluate_candidate_publishability(
        [candidate],
        _profile(),
        required_count=1,
        allow_mock=True,
    )

    assert result.ready is True
    assert result.accepted == [candidate]


def test_publishability_fails_when_destination_is_unresolved():
    result = evaluate_candidate_publishability(
        [_candidate("上海景点")],
        DestinationProfile(requested_name="未知地点"),
        required_count=1,
    )

    assert result.status == "destination_unresolved"
    assert result.reject_reason_counts == {"destination_unresolved": 1}

