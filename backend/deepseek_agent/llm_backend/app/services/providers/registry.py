from __future__ import annotations

from dataclasses import dataclass, field

from app.services.providers.base import (
    MapProvider,
    ReviewProvider,
    SearchProvider,
    WeatherProvider,
)

# 提供者注册
@dataclass(slots=True)
class ProviderRegistry:
    """Keep business flow dependent on abstractions, not concrete SDKs."""

    search_providers: list[SearchProvider] = field(default_factory=list)
    map_providers: list[MapProvider] = field(default_factory=list)
    weather_providers: list[WeatherProvider] = field(default_factory=list)
    review_providers: list[ReviewProvider] = field(default_factory=list)

    def register_search(self, provider: SearchProvider) -> None:
        self.search_providers.append(provider)

    def register_map(self, provider: MapProvider) -> None:
        self.map_providers.append(provider)

    def register_weather(self, provider: WeatherProvider) -> None:
        self.weather_providers.append(provider)

    def register_review(self, provider: ReviewProvider) -> None:
        self.review_providers.append(provider)
