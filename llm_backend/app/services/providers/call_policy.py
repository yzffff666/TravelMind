from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProviderType(str, Enum):
    SEARCH = "search"
    MAP = "map"
    WEATHER = "weather"
    REVIEW = "review"


@dataclass(slots=True)
class ProviderCallPolicy:
    """Controls how and how many times providers are called per request.

    Consumed by ``ProviderOrchestrator`` to enforce call budgets,
    timeouts, and fallback behaviour.
    """

    max_calls_per_request: int = 6
    timeout_seconds: float = 10.0

    provider_priority: list[ProviderType] = field(
        default_factory=lambda: [
            ProviderType.SEARCH,
            ProviderType.MAP,
            ProviderType.WEATHER,
            ProviderType.REVIEW,
        ]
    )

    search_enabled: bool = True
    map_enabled: bool = True
    weather_enabled: bool = False
    review_enabled: bool = False

    fallback_to_mock: bool = True

    top_k_search: int = 10
    top_k_map: int = 20

    def is_enabled(self, pt: ProviderType) -> bool:
        return {
            ProviderType.SEARCH: self.search_enabled,
            ProviderType.MAP: self.map_enabled,
            ProviderType.WEATHER: self.weather_enabled,
            ProviderType.REVIEW: self.review_enabled,
        }.get(pt, False)


DEFAULT_POLICY = ProviderCallPolicy()
