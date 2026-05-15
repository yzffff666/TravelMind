"""Agentic POI ranking policy for travel-planning candidates.

This module makes the ranking decision layer explicit:

ProviderCandidate -> CandidateFeature -> RankedPOICandidate

The policy is intentionally rule-based for now. It gives TravelMind a stable
baseline for collecting badcases before introducing semantic or learned
rankers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.geo_bounds import is_coord_within_destination
from app.services.providers.base import ProviderCandidate


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
    has_geo: bool = False
    is_generic_activity: bool = False
    is_duplicate: bool = False
    risk_flags: list[str] = field(default_factory=list)

    @classmethod
    def from_candidate(
        cls,
        candidate: ProviderCandidate,
        *,
        destination: str = "",
        preferences: list[str] | None = None,
        daily_budget: float | None = None,
        seen_titles: set[str] | None = None,
    ) -> "CandidateFeature":
        lat = _as_float(candidate.extra.get("lat"))
        lng = _as_float(candidate.extra.get("lng"))
        has_geo = lat is not None and lng is not None
        bbox_valid = (
            is_coord_within_destination(destination, lat, lng)
            if destination and has_geo
            else None
        )

        title_key = _normalize_text(candidate.title or "")
        is_duplicate = bool(title_key and seen_titles is not None and title_key in seen_titles)
        if seen_titles is not None and title_key:
            seen_titles.add(title_key)

        risk_flags: list[str] = []
        if bbox_valid is False:
            risk_flags.append("bbox_invalid")
        if not has_geo:
            risk_flags.append("missing_geo")
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
            has_geo=has_geo,
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
        preferences: list[str] | None = None,
        budget: float | None = None,
        days: int | None = None,
        top_k: int = 15,
        include_rejected: bool = False,
    ) -> list[RankedPOICandidate]:
        daily_budget = budget / days if budget is not None and days and days > 0 else None
        seen_titles: set[str] = set()
        features = [
            CandidateFeature.from_candidate(
                candidate,
                destination=destination,
                preferences=preferences,
                daily_budget=daily_budget,
                seen_titles=seen_titles,
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
        if feature.is_generic_activity:
            reasons.append("generic_activity")
        if feature.is_duplicate:
            reasons.append("duplicate_poi")
        if feature.bbox_valid is False:
            reasons.append("bbox_invalid")
        return reasons


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
