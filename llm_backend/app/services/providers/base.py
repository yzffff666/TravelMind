from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# 提供者错误代码
class ProviderErrorCode(str, Enum):
    """Normalized error codes returned by provider adapters."""

    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"
    AUTH_FAILED = "auth_failed"
    UNKNOWN = "unknown"


# 提供者错误
@dataclass(slots=True)
class ProviderError:
    """Provider-layer error payload with downgrade hints."""

    code: ProviderErrorCode
    message: str
    provider_name: str
    retryable: bool = False
    degraded: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


# 提供者调用上下文
@dataclass(slots=True)
class ProviderCallContext:
    """Execution context for provider calls."""

    request_id: str | None = None
    conversation_id: str | None = None
    user_id: int | None = None


# 提供者候选
@dataclass(slots=True)
class ProviderCandidate:
    """Standard candidate shape consumed by recall/ranking pipeline."""

    candidate_id: str
    source: str
    title: str
    snippet: str = ""
    score: float = 0.0
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


# 提供者响应
@dataclass(slots=True)
class ProviderResponse:
    """Standard provider response format."""

    candidates: list[ProviderCandidate] = field(default_factory=list)
    errors: list[ProviderError] = field(default_factory=list)
    degraded: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


# 搜索提供者
class SearchProvider(ABC):
    """Query-driven candidate retrieval provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def search(
        self,
        *,
        query: str,
        top_k: int = 10,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        pass


# 地图提供者
class MapProvider(ABC):
    """POI/geospatial data provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def nearby_poi(
        self,
        *,
        city: str,
        keywords: list[str],
        top_k: int = 20,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        pass


# 天气提供者
class WeatherProvider(ABC):
    """Weather forecast provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def forecast(
        self,
        *,
        city: str,
        date_range: str | None = None,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        pass


# 评论提供者
class ReviewProvider(ABC):
    """Review/rating provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def reviews(
        self,
        *,
        poi_names: list[str],
        top_k: int = 10,
        context: ProviderCallContext | None = None,
    ) -> ProviderResponse:
        pass
