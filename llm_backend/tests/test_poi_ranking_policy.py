"""Tests for Agentic POI ranking policy.

The policy is the first explicit bridge from provider recall results to
Agent decision quality: extract features, apply hard gates, then rank accepted
POI candidates with explainable score breakdown.
"""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings
from app.services.destination_grounding import DestinationProfile
from app.services.poi_ranking_policy import (
    CandidateFeature,
    POIRankingPolicy,
    build_ranking_shadow_report,
    policy_ranked_to_scored,
    select_runtime_ranking,
)
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import ScoredCandidate


def _candidate(
    title: str,
    *,
    source: str = "amap_search",
    score: float = 0.7,
    lat: float | None = 7.89,
    lng: float | None = 98.39,
    tags: list[str] | None = None,
    extra: dict | None = None,
) -> ProviderCandidate:
    payload = {
        "address": "Phuket address",
        "rating": 4.6,
        "url": "https://example.com/poi",
        "photos": ["https://example.com/photo.jpg"],
        "tel": "123",
        "lat": lat,
        "lng": lng,
    }
    if extra:
        payload.update(extra)
    return ProviderCandidate(
        candidate_id=f"{source}-{title}",
        source=source,
        title=title,
        snippet=f"{title} is a Phuket attraction",
        score=score,
        tags=tags or ["海边", "景点"],
        extra=payload,
    )


def test_candidate_feature_extracts_bbox_alias_and_evidence():
    candidate = _candidate("Old Phuket Town", extra={"alias_hit": True})

    feature = CandidateFeature.from_candidate(
        candidate,
        destination="普吉岛",
        preferences=["海边"],
        daily_budget=500,
    )

    assert feature.alias_hit is True
    assert feature.has_geo is True
    assert feature.bbox_valid is True
    assert feature.evidence_score > 0.6
    assert feature.preference_match == 1.0
    assert "bbox_invalid" not in feature.risk_flags


def test_policy_ranks_alias_and_evidence_rich_candidate_first():
    weak = _candidate(
        "Shopping stop",
        score=0.4,
        tags=["购物"],
        extra={"url": "", "photos": [], "tel": ""},
    )
    strong = _candidate(
        "Kata Beach",
        score=0.8,
        tags=["海边"],
        extra={"alias_hit": True, "provider_confidence": 0.9},
    )

    ranked = POIRankingPolicy().rank(
        [weak, strong],
        destination="普吉岛",
        preferences=["海边"],
        budget=3000,
        days=3,
    )

    assert [item.candidate.title for item in ranked] == ["Kata Beach", "Shopping stop"]
    assert ranked[0].accepted is True
    assert ranked[0].score_breakdown["alias_bonus"] == 1.0


def test_policy_rejects_out_of_bbox_candidate():
    paris = _candidate("Eiffel Tower", lat=48.8584, lng=2.2945)

    ranked = POIRankingPolicy().rank(
        [paris],
        destination="普吉岛",
        include_rejected=True,
    )

    assert ranked[0].accepted is False
    assert "bbox_invalid" in ranked[0].reject_reasons
    assert ranked[0].feature.distance_feasibility == 0.0


def test_policy_rejects_duplicate_candidate_but_can_audit_it():
    first = _candidate("Kata Beach")
    duplicate = _candidate(" Kata  Beach ", score=0.95)

    ranked = POIRankingPolicy().rank(
        [first, duplicate],
        destination="普吉岛",
        include_rejected=True,
    )

    assert ranked[0].accepted is True
    assert ranked[1].accepted is False
    assert "duplicate_poi" in ranked[1].reject_reasons


def test_policy_rejects_generic_activity_candidate():
    generic = _candidate("第1天核心景点参观")

    ranked = POIRankingPolicy().rank(
        [generic],
        destination="普吉岛",
        include_rejected=True,
    )

    assert ranked[0].accepted is False
    assert "generic_activity" in ranked[0].reject_reasons


def test_policy_rejects_missing_geo_even_when_text_matches_destination():
    candidate = _candidate("Phuket Museum", lat=None, lng=None)

    ranked = POIRankingPolicy().rank(
        [candidate],
        destination="普吉岛",
        include_rejected=True,
    )

    assert ranked[0].accepted is False
    assert "missing_geo" in ranked[0].reject_reasons


def test_policy_uses_dynamic_destination_profile_radius():
    tokyo = DestinationProfile(
        requested_name="东京",
        canonical_name="Tokyo",
        country="Japan",
        center_lat=35.6762,
        center_lng=139.6503,
        radius_km=40,
        confidence=0.95,
        source="fixture",
        is_dynamic=True,
    )
    osaka = _candidate("Osaka Castle", lat=34.6873, lng=135.5262)

    ranked = POIRankingPolicy().rank(
        [osaka],
        destination_profile=tokyo,
        include_rejected=True,
    )

    assert ranked[0].accepted is False
    assert "outside_destination_radius" in ranked[0].reject_reasons


def test_runtime_mode_selects_candidate_or_legacy_order_and_adapts_contract():
    weak = _candidate("Shopping stop", score=0.95, tags=["购物"], extra={"url": "", "photos": [], "tel": ""})
    strong = _candidate("Kata Beach", score=0.70, tags=["海边"], extra={"alias_hit": True})
    legacy = [
        ScoredCandidate(candidate=weak, total_score=0.95),
        ScoredCandidate(candidate=strong, total_score=0.70),
    ]
    policy = POIRankingPolicy().rank(
        [weak, strong],
        destination="普吉岛",
        preferences=["海边"],
        include_rejected=True,
    )

    candidate_ranked = select_runtime_ranking("candidate", legacy, policy)
    shadow_ranked = select_runtime_ranking("shadow", legacy, policy)

    assert [item.candidate.title for item in candidate_ranked] == ["Kata Beach", "Shopping stop"]
    assert [item.candidate.title for item in shadow_ranked] == ["Shopping stop", "Kata Beach"]
    assert policy_ranked_to_scored(policy)[0].breakdown["alias_bonus"] == 1.0


def test_runtime_mode_rejects_invalid_value():
    annotation = Settings.model_fields["POI_RANKING_MODE"].annotation
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python("unknown")
    with pytest.raises(ValueError):
        select_runtime_ranking("unknown", [], [])


def test_shadow_report_summarizes_legacy_vs_policy_decisions():
    accepted = _candidate("Kata Beach", extra={"alias_hit": True})
    rejected = _candidate("Eiffel Tower", lat=48.8584, lng=2.2945)
    legacy_ranked = [
        ScoredCandidate(candidate=rejected, total_score=0.95),
        ScoredCandidate(candidate=accepted, total_score=0.80),
    ]
    policy_ranked = POIRankingPolicy().rank(
        [rejected, accepted],
        destination="普吉岛",
        include_rejected=True,
    )

    report = build_ranking_shadow_report(
        destination="普吉岛",
        recalled_count=2,
        legacy_ranked=legacy_ranked,
        policy_ranked=policy_ranked,
    )

    assert report["event_type"] == "poi_ranking_shadow"
    assert report["policy_accepted_count"] == 1
    assert report["policy_rejected_count"] == 1
    assert report["reject_reason_counts"] == {"bbox_invalid": 1}
    assert report["legacy_top"][0]["title"] == "Eiffel Tower"
    assert report["policy_top"][0]["title"] == "Kata Beach"
    assert report["rejected_samples"][0]["reject_reasons"] == ["bbox_invalid"]
    assert report["rejected_samples"][0]["lat"] == 48.8584
    assert report["rejected_samples"][0]["lng"] == 2.2945
    assert report["rejected_samples"][0]["address"] == "Phuket address"
    assert report["rejected_samples"][0]["score_breakdown"]["distance_feasibility"] == 0.0
