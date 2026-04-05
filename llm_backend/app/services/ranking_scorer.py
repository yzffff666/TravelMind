"""Explainable rule-based ranking scorer for travel POI candidates.

Design reference: ``docs/下层能力流水线技术方案.md`` §4.3

Scoring dimensions (all normalized to [0, 1]):
- preference_match:  user preferences vs candidate tags (hit rate)
- budget_fit:        user budget vs candidate cost_estimate (proximity)
- rating:            API-returned rating normalized to [0, 1]
- popularity:        review count log-scaled and normalized
- evidence_quality:  completeness of supporting fields (url, snippet, rating, address)

total_score = Σ (weight_i × score_i)

All per-dimension scores are preserved in ``ScoredCandidate.breakdown``
for downstream explainability and debugging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import log1p
from typing import Any

from app.services.providers.base import ProviderCandidate


@dataclass(slots=True)
class RankingWeights:
    """Configurable weights for each scoring dimension.

    All weights should be non-negative. They are automatically
    normalized to sum to 1.0 at scoring time.
    """

    preference_match: float = 0.30
    budget_fit: float = 0.25
    rating: float = 0.20
    popularity: float = 0.10
    evidence_quality: float = 0.15

    def normalized(self) -> dict[str, float]:
        raw = {
            "preference_match": self.preference_match,
            "budget_fit": self.budget_fit,
            "rating": self.rating,
            "popularity": self.popularity,
            "evidence_quality": self.evidence_quality,
        }
        total = sum(raw.values())
        if total <= 0:
            count = len(raw)
            return {k: 1.0 / count for k in raw}
        return {k: v / total for k, v in raw.items()}


DEFAULT_WEIGHTS = RankingWeights()

_EVIDENCE_FIELDS = ("url", "address", "rating", "website", "photos", "tel")
_MAX_RATING = 5.0
_LOG_POP_CAP = log1p(50000)


@dataclass(slots=True)
class ScoredCandidate:
    """A candidate enriched with per-dimension scores and total score."""

    candidate: ProviderCandidate
    total_score: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)


def _preference_score(candidate: ProviderCandidate, preferences: list[str]) -> float:
    """Hit rate: fraction of user preferences matched in candidate tags."""
    if not preferences:
        return 0.5
    tags_lower = {t.lower() for t in candidate.tags}
    snippet_lower = (candidate.snippet + candidate.title).lower()
    hits = sum(
        1 for p in preferences
        if p.lower() in tags_lower or p.lower() in snippet_lower
    )
    return hits / len(preferences)


def _budget_score(candidate: ProviderCandidate, daily_budget: float | None) -> float:
    """Proximity score: closer to daily budget → higher score.

    Formula: 1 - |cost - daily_budget| / daily_budget, clamped to [0, 1].
    No budget info → neutral 0.5.
    """
    if daily_budget is None or daily_budget <= 0:
        return 0.5

    cost = candidate.extra.get("cost_estimate", 0.0)
    if not cost or cost <= 0:
        return 0.5

    diff_ratio = abs(cost - daily_budget) / daily_budget
    return max(0.0, min(1.0, 1.0 - diff_ratio))


def _rating_score(candidate: ProviderCandidate) -> float:
    """Normalize rating to [0, 1]. Max assumed rating is 5.0."""
    rating = candidate.extra.get("rating", 0.0) or candidate.score * _MAX_RATING
    if not rating or rating <= 0:
        return 0.3
    return min(float(rating) / _MAX_RATING, 1.0)


def _popularity_score(candidate: ProviderCandidate) -> float:
    """Log-scaled review count, capped and normalized."""
    reviews = candidate.extra.get("reviews_count", 0) or candidate.extra.get("reviews", 0)
    if not reviews or reviews <= 0:
        return 0.2
    return min(log1p(float(reviews)) / _LOG_POP_CAP, 1.0)


def _evidence_score(candidate: ProviderCandidate) -> float:
    """Fraction of evidence-supporting fields present in extra."""
    present = sum(
        1 for f in _EVIDENCE_FIELDS
        if candidate.extra.get(f) not in (None, "", [], 0, 0.0)
    )
    return present / len(_EVIDENCE_FIELDS)


class RankingScorer:
    """Stateless, configurable scorer for ranking recalled candidates.

    Usage::

        scorer = RankingScorer(weights=DEFAULT_WEIGHTS)
        ranked = scorer.rank(
            candidates=recall_result.candidates,
            preferences=["美食", "文化"],
            budget=6000,
            days=4,
            top_k=15,
        )
        # ranked is a list of ScoredCandidate, sorted by total_score desc
    """

    def __init__(self, weights: RankingWeights | None = None) -> None:
        self._weights = weights or DEFAULT_WEIGHTS

    def score_one(
        self,
        candidate: ProviderCandidate,
        *,
        preferences: list[str] | None = None,
        daily_budget: float | None = None,
    ) -> ScoredCandidate:
        """Score a single candidate and return breakdown."""
        w = self._weights.normalized()

        breakdown = {
            "preference_match": _preference_score(candidate, preferences or []),
            "budget_fit": _budget_score(candidate, daily_budget),
            "rating": _rating_score(candidate),
            "popularity": _popularity_score(candidate),
            "evidence_quality": _evidence_score(candidate),
        }

        total = sum(w[dim] * breakdown[dim] for dim in breakdown)

        return ScoredCandidate(
            candidate=candidate,
            total_score=round(total, 4),
            breakdown={k: round(v, 4) for k, v in breakdown.items()},
        )

    def rank(
        self,
        candidates: list[ProviderCandidate],
        *,
        preferences: list[str] | None = None,
        budget: float | None = None,
        days: int | None = None,
        top_k: int = 15,
    ) -> list[ScoredCandidate]:
        """Score all candidates, sort descending, return top-K.

        Parameters
        ----------
        candidates : recalled ProviderCandidate list
        preferences : user preference keywords from QP
        budget : total trip budget from QP
        days : trip duration from QP (used to derive daily budget)
        top_k : max results to return
        """
        daily_budget = None
        if budget is not None and days and days > 0:
            daily_budget = budget / days

        scored = [
            self.score_one(c, preferences=preferences, daily_budget=daily_budget)
            for c in candidates
        ]

        scored.sort(key=lambda s: s.total_score, reverse=True)
        return scored[:top_k]

    def rank_from_qp(
        self,
        candidates: list[ProviderCandidate],
        qp_output: dict[str, Any],
        *,
        top_k: int = 15,
    ) -> list[ScoredCandidate]:
        """Convenience: rank using structured QP output dict."""
        constraints = qp_output.get("constraints", {})
        return self.rank(
            candidates,
            preferences=constraints.get("preferences"),
            budget=constraints.get("budget"),
            days=constraints.get("days"),
            top_k=top_k,
        )
