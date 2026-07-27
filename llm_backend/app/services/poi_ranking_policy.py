"""Agentic POI ranking policy for travel-planning candidates.

This module makes the ranking decision layer explicit:

ProviderCandidate -> CandidateFeature -> RankedPOICandidate

The policy is intentionally rule-based for now. It gives TravelMind a stable
baseline for collecting badcases before introducing semantic or learned
rankers.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.services.destination_grounding import (
    DestinationProfile,
    has_valid_coordinates,
    validate_candidate_destination,
)
from app.services.geo_bounds import is_coord_within_destination
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import ScoredCandidate


_EVIDENCE_FIELDS = ("url", "address", "rating", "website", "photos", "tel")
_GENERIC_ACTIVITY_TERMS = (
    "活动",
    "休闲",
    "漫步",
    "打卡",
    "景点参观",
    "美食与休闲",
    "核心景点",
    "随便玩",
    "activity",
    "leisure",
    "sightseeing",
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _as_float(value: Any) -> float | None:
    if value in (None, "", [], {}):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: str) -> str:
    return "".join(ch.lower() for ch in value.strip() if not ch.isspace())


@dataclass(slots=True)
class CandidateFeature:
    """Normalized features consumed by the POI ranking policy."""

    candidate: ProviderCandidate
    destination: str = ""
    preference_match: float = 0.5
    budget_match: float = 0.5
    distance_feasibility: float = 0.5
    evidence_score: float = 0.0
    provider_confidence: float = 0.5
    resolvable_score: float = 0.5
    alias_hit: bool = False
    bbox_valid: bool | None = None
    destination_grounding_reason: str | None = None
    has_geo: bool = False
    mock_disallowed: bool = False
    is_generic_activity: bool = False
    is_duplicate: bool = False
    risk_flags: list[str] = field(default_factory=list)

    @classmethod
    def from_candidate(
        cls,
        candidate: ProviderCandidate,
        *,
        destination: str = "",
        destination_profile: DestinationProfile | None = None,
        preferences: list[str] | None = None,
        daily_budget: float | None = None,
        seen_titles: set[str] | None = None,
        allow_mock: bool = False,
    ) -> "CandidateFeature":
        lat = _as_float(candidate.extra.get("lat"))
        lng = _as_float(candidate.extra.get("lng"))
        has_geo = has_valid_coordinates(candidate)
        grounding_reason: str | None = None
        if destination_profile is not None and has_geo:
            grounding = validate_candidate_destination(candidate, destination_profile)
            bbox_valid = grounding.accepted
            if not grounding.accepted:
                grounding_reason = grounding.reason
        else:
            bbox_valid = (
                is_coord_within_destination(destination, lat, lng)
                if destination and has_geo and lat is not None and lng is not None
                else None
            )
            if bbox_valid is False:
                grounding_reason = "bbox_invalid"

        title_key = _normalize_text(candidate.title or "")
        is_duplicate = bool(title_key and seen_titles is not None and title_key in seen_titles)
        if seen_titles is not None and title_key:
            seen_titles.add(title_key)

        risk_flags: list[str] = []
        if not has_geo:
            risk_flags.append("missing_geo")
        elif grounding_reason:
            risk_flags.append(grounding_reason)
        if is_duplicate:
            risk_flags.append("duplicate_poi")

        is_generic = _is_generic_activity(candidate)
        if is_generic:
            risk_flags.append("generic_activity")

        alias_hit = bool(
            candidate.extra.get("alias_hit")
            or candidate.extra.get("matched_alias")
            or candidate.extra.get("alias")
        )

        return cls(
            candidate=candidate,
            destination=destination,
            preference_match=_preference_match(candidate, preferences or []),
            budget_match=_budget_match(candidate, daily_budget),
            distance_feasibility=1.0 if bbox_valid is not False else 0.0,
            evidence_score=_evidence_score(candidate),
            provider_confidence=_provider_confidence(candidate),
            resolvable_score=_resolvable_score(candidate, has_geo=has_geo, alias_hit=alias_hit),
            alias_hit=alias_hit,
            bbox_valid=bbox_valid,
            destination_grounding_reason=grounding_reason,
            has_geo=has_geo,
            mock_disallowed=candidate.source.lower().startswith("mock") and not allow_mock,
            is_generic_activity=is_generic,
            is_duplicate=is_duplicate,
            risk_flags=risk_flags,
        )


@dataclass(slots=True)
class POIRankingWeights:
    """Weights for soft ranking after hard gates are evaluated."""

    resolvable_score: float = 0.25
    evidence_score: float = 0.20
    preference_match: float = 0.20
    provider_confidence: float = 0.15
    distance_feasibility: float = 0.10
    budget_match: float = 0.10
    alias_bonus: float = 0.05


@dataclass(slots=True)
class RankedPOICandidate:
    """Candidate decision with ranking score and explainable reasons."""

    feature: CandidateFeature
    rank_score: float
    accepted: bool
    reject_reasons: list[str] = field(default_factory=list)
    score_breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def candidate(self) -> ProviderCandidate:
        return self.feature.candidate


class POIRankingPolicy:
    """Hard-gate plus soft-score ranking for Agent POI decisions."""

    def __init__(self, weights: POIRankingWeights | None = None) -> None:
        self._weights = weights or POIRankingWeights()

    def rank(
        self,
        candidates: list[ProviderCandidate],
        *,
        destination: str = "",
        destination_profile: DestinationProfile | None = None,
        preferences: list[str] | None = None,
        budget: float | None = None,
        days: int | None = None,
        top_k: int = 15,
        include_rejected: bool = False,
        allow_mock: bool = False,
    ) -> list[RankedPOICandidate]:
        effective_destination = (
            destination_profile.canonical_name
            if destination_profile is not None
            else destination
        )
        daily_budget = budget / days if budget is not None and days and days > 0 else None
        seen_titles: set[str] = set()
        features = [
            CandidateFeature.from_candidate(
                candidate,
                destination=effective_destination,
                destination_profile=destination_profile,
                preferences=preferences,
                daily_budget=daily_budget,
                seen_titles=seen_titles,
                allow_mock=allow_mock,
            )
            for candidate in candidates
        ]
        return self.rank_features(features, top_k=top_k, include_rejected=include_rejected)

    def rank_features(
        self,
        features: list[CandidateFeature],
        *,
        top_k: int = 15,
        include_rejected: bool = False,
    ) -> list[RankedPOICandidate]:
        ranked = [self.score_one(feature) for feature in features]
        ranked.sort(key=lambda item: (item.accepted, item.rank_score), reverse=True)
        if include_rejected:
            return ranked[:top_k]
        return [item for item in ranked if item.accepted][:top_k]

    def score_one(self, feature: CandidateFeature) -> RankedPOICandidate:
        reject_reasons = self._hard_gate(feature)
        breakdown = {
            "resolvable_score": feature.resolvable_score,
            "evidence_score": feature.evidence_score,
            "preference_match": feature.preference_match,
            "provider_confidence": feature.provider_confidence,
            "distance_feasibility": feature.distance_feasibility,
            "budget_match": feature.budget_match,
            "alias_bonus": 1.0 if feature.alias_hit else 0.0,
        }
        total = (
            self._weights.resolvable_score * breakdown["resolvable_score"]
            + self._weights.evidence_score * breakdown["evidence_score"]
            + self._weights.preference_match * breakdown["preference_match"]
            + self._weights.provider_confidence * breakdown["provider_confidence"]
            + self._weights.distance_feasibility * breakdown["distance_feasibility"]
            + self._weights.budget_match * breakdown["budget_match"]
            + self._weights.alias_bonus * breakdown["alias_bonus"]
        )
        if reject_reasons:
            total *= 0.25

        return RankedPOICandidate(
            feature=feature,
            rank_score=round(_clamp01(total), 4),
            accepted=not reject_reasons,
            reject_reasons=reject_reasons,
            score_breakdown={key: round(value, 4) for key, value in breakdown.items()},
        )

    @staticmethod
    def _hard_gate(feature: CandidateFeature) -> list[str]:
        reasons: list[str] = []
        if not feature.has_geo:
            reasons.append("missing_geo")
        if feature.mock_disallowed:
            reasons.append("mock_candidate")
        if feature.is_generic_activity:
            reasons.append("generic_activity")
        if feature.is_duplicate:
            reasons.append("duplicate_poi")
        if feature.destination_grounding_reason:
            reasons.append(feature.destination_grounding_reason)
        return reasons


def policy_ranked_to_scored(
    ranked: list[RankedPOICandidate],
) -> list[ScoredCandidate]:
    """Adapt accepted policy decisions to the planner's stable input contract."""
    return [
        ScoredCandidate(
            candidate=item.candidate,
            total_score=item.rank_score,
            breakdown=dict(item.score_breakdown),
        )
        for item in ranked
        if item.accepted
    ]


def select_runtime_ranking(
    mode: str,
    legacy_ranked: list[ScoredCandidate],
    policy_ranked: list[RankedPOICandidate],
) -> list[ScoredCandidate]:
    """Select the planner input while keeping rollout reversible."""
    if mode == "candidate":
        return policy_ranked_to_scored(policy_ranked)
    if mode in {"legacy", "shadow"}:
        return legacy_ranked
    raise ValueError(f"Unsupported POI ranking mode: {mode}")


def build_ranking_shadow_report(
    *,
    destination: str,
    recalled_count: int,
    legacy_ranked: list[Any],
    policy_ranked: list[RankedPOICandidate],
    top_k: int = 5,
) -> dict[str, Any]:
    """Summarize old ranking vs new policy ranking without changing runtime output."""
    legacy_top = [_candidate_summary(item.candidate) for item in legacy_ranked[:top_k]]
    accepted = [item for item in policy_ranked if item.accepted]
    rejected = [item for item in policy_ranked if not item.accepted]
    policy_top = [
        {
            **_candidate_summary(item.candidate),
            "rank_score": item.rank_score,
            "score_breakdown": item.score_breakdown,
        }
        for item in accepted[:top_k]
    ]

    legacy_ids = {item["candidate_id"] for item in legacy_top if item.get("candidate_id")}
    policy_ids = {item["candidate_id"] for item in policy_top if item.get("candidate_id")}
    overlap_denominator = min(len(legacy_ids), len(policy_ids), top_k) or 1
    overlap_count = len(legacy_ids & policy_ids)
    reason_counts = Counter(reason for item in rejected for reason in item.reject_reasons)

    return {
        "event_type": "poi_ranking_shadow",
        "destination": destination,
        "recalled_count": recalled_count,
        "legacy_ranked_count": len(legacy_ranked),
        "policy_ranked_count": len(policy_ranked),
        "policy_accepted_count": len(accepted),
        "policy_rejected_count": len(rejected),
        "top_k": top_k,
        "top_k_overlap_count": overlap_count,
        "top_k_overlap_rate": round(overlap_count / overlap_denominator, 4),
        "reject_reason_counts": dict(reason_counts),
        "legacy_top": legacy_top,
        "policy_top": policy_top,
        "rejected_samples": [
            {
                **_candidate_summary(item.candidate),
                "rank_score": item.rank_score,
                "score_breakdown": item.score_breakdown,
                "reject_reasons": item.reject_reasons,
                "risk_flags": item.feature.risk_flags,
            }
            for item in rejected[:top_k]
        ],
    }


def _candidate_summary(candidate: ProviderCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "title": candidate.title,
        "source": candidate.source,
        "score": round(float(candidate.score or 0.0), 4),
        "lat": _as_float(candidate.extra.get("lat")),
        "lng": _as_float(candidate.extra.get("lng")),
        "address": candidate.extra.get("address"),
    }


def _preference_match(candidate: ProviderCandidate, preferences: list[str]) -> float:
    if not preferences:
        return 0.5
    haystack = " ".join([
        candidate.title or "",
        candidate.snippet or "",
        " ".join(candidate.tags or []),
    ]).lower()
    hits = sum(1 for pref in preferences if pref and pref.lower() in haystack)
    return hits / len(preferences)


def _budget_match(candidate: ProviderCandidate, daily_budget: float | None) -> float:
    if daily_budget is None or daily_budget <= 0:
        return 0.5
    cost = _as_float(candidate.extra.get("cost_estimate"))
    if cost is None or cost <= 0:
        return 0.5
    return _clamp01(1.0 - abs(cost - daily_budget) / daily_budget)


def _evidence_score(candidate: ProviderCandidate) -> float:
    present = sum(
        1 for field_name in _EVIDENCE_FIELDS
        if candidate.extra.get(field_name) not in (None, "", [], 0, 0.0)
    )
    return present / len(_EVIDENCE_FIELDS)


def _provider_confidence(candidate: ProviderCandidate) -> float:
    explicit = _as_float(candidate.extra.get("provider_confidence"))
    if explicit is not None:
        return _clamp01(explicit)
    base = _clamp01(candidate.score or 0.0)
    if candidate.source.startswith("amap"):
        base = max(base, 0.65)
    elif candidate.source.startswith("mock"):
        base = min(base, 0.45)
    return base or 0.5


def _resolvable_score(
    candidate: ProviderCandidate,
    *,
    has_geo: bool,
    alias_hit: bool,
) -> float:
    score = 0.25
    if candidate.title:
        score += 0.25
    if has_geo:
        score += 0.30
    if alias_hit:
        score += 0.10
    if candidate.extra.get("address"):
        score += 0.10
    return _clamp01(score)


def _is_generic_activity(candidate: ProviderCandidate) -> bool:
    explicit = candidate.extra.get("is_generic_activity")
    if explicit is not None:
        return bool(explicit)
    text = _normalize_text(" ".join([candidate.title or "", candidate.snippet or ""]))
    if not text:
        return True
    return any(term.lower().replace(" ", "") in text for term in _GENERIC_ACTIVITY_TERMS)
