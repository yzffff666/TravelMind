"""Shared publish gate for candidate-driven itinerary decisions."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.services.destination_grounding import (
    DestinationProfile,
    has_valid_coordinates,
    validate_candidate_destination,
)
from app.services.providers.base import ProviderCandidate


@dataclass(slots=True)
class PublishabilityResult:
    accepted: list[ProviderCandidate]
    status: str
    required_count: int
    reject_reason_counts: dict[str, int]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


def evaluate_candidate_publishability(
    candidates: list[ProviderCandidate],
    profile: DestinationProfile,
    *,
    required_count: int,
    allow_mock: bool = False,
) -> PublishabilityResult:
    """Return coordinate-backed local candidates that may enter planning."""
    required = max(1, int(required_count))
    if not profile.resolved:
        return PublishabilityResult(
            accepted=[],
            status="destination_unresolved",
            required_count=required,
            reject_reason_counts={"destination_unresolved": 1},
        )

    accepted: list[ProviderCandidate] = []
    rejected: Counter[str] = Counter()
    for candidate in candidates:
        if not has_valid_coordinates(candidate):
            rejected["missing_geo"] += 1
            continue
        if candidate.source.lower().startswith("mock") and not allow_mock:
            rejected["mock_candidate"] += 1
            continue

        grounding = validate_candidate_destination(candidate, profile)
        candidate.extra["destination_grounding"] = grounding.to_dict()
        if not grounding.accepted:
            rejected[grounding.reason] += 1
            continue
        accepted.append(candidate)

    status = "ready" if len(accepted) >= required else "insufficient_candidates"
    return PublishabilityResult(
        accepted=accepted,
        status=status,
        required_count=required,
        reject_reason_counts=dict(rejected),
    )

