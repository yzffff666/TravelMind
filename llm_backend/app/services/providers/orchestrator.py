from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.logger import get_logger
from app.services.providers.base import (
    MapProvider,
    ProviderCallContext,
    ProviderCandidate,
    ProviderError,
    ProviderErrorCode,
    ProviderResponse,
    SearchProvider,
)
from app.services.providers.call_policy import ProviderCallPolicy, ProviderType
from app.services.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)
structured_logger = get_logger(service="provider_orchestrator")

from app.core.config import settings as _settings
_RECALL_CACHE_TTL = _settings.REDIS_CACHE_EXPIRE
_recall_cache: dict[str, tuple[float, "OrchestratorResult"]] = {}


def clear_recall_cache() -> None:
    """Clear the in-memory recall cache (useful for testing)."""
    _recall_cache.clear()


def _cache_key(query: str, city: str, keywords: list[str] | None) -> str:
    raw = f"{city}|{query}|{sorted(keywords or [])}"
    return hashlib.md5(raw.encode()).hexdigest()


@dataclass
class _ProviderOutcome:
    """Result of a single parallel provider call."""
    provider_name: str
    provider_kind: str
    elapsed_ms: float
    result_count: int = 0
    response: ProviderResponse | None = None
    error_code: ProviderErrorCode | None = None
    error_message: str = ""


@dataclass
class OrchestratorResult:
    """Aggregated result from all provider calls in one request."""

    candidates: list[ProviderCandidate] = field(default_factory=list)
    errors: list[ProviderError] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    degraded: bool = False
    calls_made: int = 0


class ProviderOrchestrator:
    """Executes provider calls respecting call budget and timeouts.

    All providers are called in parallel via ``asyncio.gather`` to
    minimise wall-clock latency.  Individual failures are isolated —
    the orchestrator records a ``ProviderError``, marks the result as
    *degraded*, and appends a human-readable assumption string so
    downstream nodes can surface it in ``validation.assumptions``.
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        policy: ProviderCallPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy or ProviderCallPolicy()

    async def recall(
        self,
        *,
        query: str,
        city: str,
        keywords: list[str] | None = None,
        context: ProviderCallContext | None = None,
    ) -> OrchestratorResult:
        """Run search + map recall within the call budget (with TTL cache).

        Provider calls are dispatched in parallel with ``asyncio.gather``.
        """
        key = _cache_key(query, city, keywords)
        cached = _recall_cache.get(key)
        if cached:
            ts, cached_result = cached
            if time.time() - ts < _RECALL_CACHE_TTL:
                logger.info("Recall cache hit for %s/%s", city, query[:30])
                return cached_result
            del _recall_cache[key]

        budget = self._policy.max_calls_per_request
        tasks: list[asyncio.Task] = []

        if self._policy.is_enabled(ProviderType.SEARCH):
            for sp in self._registry.search_providers:
                if len(tasks) >= budget:
                    break
                tasks.append(
                    asyncio.ensure_future(
                        self._call_search_safe(sp, query, context)
                    )
                )

        if self._policy.is_enabled(ProviderType.MAP):
            kw = keywords or [query]
            for mp in self._registry.map_providers:
                if len(tasks) >= budget:
                    break
                tasks.append(
                    asyncio.ensure_future(
                        self._call_map_safe(mp, city, kw, context)
                    )
                )

        outcomes: list[_ProviderOutcome] = await asyncio.gather(*tasks)

        result = OrchestratorResult(calls_made=len(tasks))
        for outcome in outcomes:
            if outcome.response is not None:
                self._merge_response(outcome.response, result, outcome.provider_name)
            elif outcome.error_code is not None:
                self._record_failure(
                    result, outcome.provider_name,
                    outcome.error_code, outcome.error_message,
                )

        if len(tasks) >= budget:
            result.assumptions.append("已达到单次请求调用上限，部分数据源未调用。")

        if not result.candidates:
            result.degraded = True
            result.assumptions.append(
                "所有数据源均不可用或无匹配结果，行程基于 AI 知识生成，实际信息请自行核实。"
            )

        result.candidates = self._dedup(result.candidates)

        if not result.degraded:
            _recall_cache[key] = (time.time(), result)

        return result

    # ------------------------------------------------------------------
    # Parallel-safe provider wrappers (return value, no side effects)
    # ------------------------------------------------------------------

    async def _call_search_safe(
        self,
        provider: SearchProvider,
        query: str,
        context: ProviderCallContext | None,
    ) -> _ProviderOutcome:
        started = time.perf_counter()
        try:
            resp = await asyncio.wait_for(
                provider.search(
                    query=query,
                    top_k=self._policy.top_k_search,
                    context=context,
                ),
                timeout=self._policy.timeout_seconds,
            )
            elapsed_ms = self._elapsed_ms(started)
            self._log_provider_call(
                provider_name=provider.name,
                provider_kind="search",
                destination=None,
                query=query,
                elapsed_ms=elapsed_ms,
                status="success",
                result_count=len(resp.candidates),
                context=context,
                degraded=resp.degraded,
                cache_source=resp.meta.get("cache_source"),
                provider_cost_tier=resp.meta.get("provider_cost_tier"),
            )
            return _ProviderOutcome(
                provider_name=provider.name,
                provider_kind="search",
                elapsed_ms=elapsed_ms,
                result_count=len(resp.candidates),
                response=resp,
            )
        except asyncio.TimeoutError:
            elapsed_ms = self._elapsed_ms(started)
            self._log_provider_call(
                provider_name=provider.name,
                provider_kind="search",
                destination=None,
                query=query,
                elapsed_ms=elapsed_ms,
                status="timeout",
                context=context,
                error_type="TimeoutError",
                error_message="搜索服务超时",
                degraded=True,
                provider_cost_tier=self._provider_cost_tier(provider.name),
            )
            return _ProviderOutcome(
                provider_name=provider.name,
                provider_kind="search",
                elapsed_ms=elapsed_ms,
                error_code=ProviderErrorCode.TIMEOUT,
                error_message="搜索服务超时",
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = self._elapsed_ms(started)
            self._log_provider_call(
                provider_name=provider.name,
                provider_kind="search",
                destination=None,
                query=query,
                elapsed_ms=elapsed_ms,
                status="error",
                context=context,
                error_type=type(exc).__name__,
                error_message=str(exc),
                degraded=True,
                provider_cost_tier=self._provider_cost_tier(provider.name),
            )
            return _ProviderOutcome(
                provider_name=provider.name,
                provider_kind="search",
                elapsed_ms=elapsed_ms,
                error_code=ProviderErrorCode.UNKNOWN,
                error_message=str(exc),
            )

    async def _call_map_safe(
        self,
        provider: MapProvider,
        city: str,
        keywords: list[str],
        context: ProviderCallContext | None,
    ) -> _ProviderOutcome:
        started = time.perf_counter()
        try:
            resp = await asyncio.wait_for(
                provider.nearby_poi(
                    city=city,
                    keywords=keywords,
                    top_k=self._policy.top_k_map,
                    context=context,
                ),
                timeout=self._policy.timeout_seconds,
            )
            elapsed_ms = self._elapsed_ms(started)
            self._log_provider_call(
                provider_name=provider.name,
                provider_kind="map",
                destination=city,
                query=" ".join(keywords),
                elapsed_ms=elapsed_ms,
                status="success",
                result_count=len(resp.candidates),
                context=context,
                degraded=resp.degraded,
                cache_source=resp.meta.get("cache_source"),
                provider_cost_tier=resp.meta.get("provider_cost_tier"),
            )
            return _ProviderOutcome(
                provider_name=provider.name,
                provider_kind="map",
                elapsed_ms=elapsed_ms,
                result_count=len(resp.candidates),
                response=resp,
            )
        except asyncio.TimeoutError:
            elapsed_ms = self._elapsed_ms(started)
            self._log_provider_call(
                provider_name=provider.name,
                provider_kind="map",
                destination=city,
                query=" ".join(keywords),
                elapsed_ms=elapsed_ms,
                status="timeout",
                context=context,
                error_type="TimeoutError",
                error_message="地图服务超时",
                degraded=True,
                provider_cost_tier=self._provider_cost_tier(provider.name),
            )
            return _ProviderOutcome(
                provider_name=provider.name,
                provider_kind="map",
                elapsed_ms=elapsed_ms,
                error_code=ProviderErrorCode.TIMEOUT,
                error_message="地图服务超时",
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = self._elapsed_ms(started)
            self._log_provider_call(
                provider_name=provider.name,
                provider_kind="map",
                destination=city,
                query=" ".join(keywords),
                elapsed_ms=elapsed_ms,
                status="error",
                context=context,
                error_type=type(exc).__name__,
                error_message=str(exc),
                degraded=True,
                provider_cost_tier=self._provider_cost_tier(provider.name),
            )
            return _ProviderOutcome(
                provider_name=provider.name,
                provider_kind="map",
                elapsed_ms=elapsed_ms,
                error_code=ProviderErrorCode.UNKNOWN,
                error_message=str(exc),
            )

    # ------------------------------------------------------------------
    # Legacy sequential wrappers (kept for backward compat in tests)
    # ------------------------------------------------------------------

    async def _call_search(
        self,
        provider: SearchProvider,
        query: str,
        context: ProviderCallContext | None,
        result: OrchestratorResult,
    ) -> None:
        outcome = await self._call_search_safe(provider, query, context)
        result.calls_made += 1
        if outcome.response is not None:
            self._merge_response(outcome.response, result, outcome.provider_name)
        elif outcome.error_code is not None:
            self._record_failure(result, outcome.provider_name, outcome.error_code, outcome.error_message)

    async def _call_map(
        self,
        provider: MapProvider,
        city: str,
        keywords: list[str],
        context: ProviderCallContext | None,
        result: OrchestratorResult,
    ) -> None:
        outcome = await self._call_map_safe(provider, city, keywords, context)
        result.calls_made += 1
        if outcome.response is not None:
            self._merge_response(outcome.response, result, outcome.provider_name)
        elif outcome.error_code is not None:
            self._record_failure(result, outcome.provider_name, outcome.error_code, outcome.error_message)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    def _log_provider_call(
        self,
        *,
        provider_name: str,
        provider_kind: str,
        destination: str | None,
        query: str,
        elapsed_ms: float,
        status: str,
        context: ProviderCallContext | None,
        result_count: int = 0,
        error_type: str = "",
        error_message: str = "",
        degraded: bool = False,
        cache_source: str | None = None,
        provider_cost_tier: str | None = None,
    ) -> None:
        structured_logger.info(
            "provider_call",
            extra={
                "event_type": "provider_call",
                "request_id": context.request_id if context else None,
                "conversation_id": context.conversation_id if context else None,
                "provider_name": provider_name,
                "provider_kind": provider_kind,
                "destination": destination,
                "query": query,
                "timeout_ms": int(self._policy.timeout_seconds * 1000),
                "elapsed_ms": elapsed_ms,
                "status": status,
                "result_count": result_count,
                "error_type": error_type,
                "error_message": error_message,
                "degraded": degraded,
                "cache_source": cache_source,
                "provider_cost_tier": provider_cost_tier,
            },
        )

    @staticmethod
    def _provider_cost_tier(provider_name: str) -> str | None:
        if provider_name.startswith("serp_"):
            return "expensive"
        return None

    @staticmethod
    def _merge_response(
        resp: ProviderResponse,
        result: OrchestratorResult,
        provider_name: str,
    ) -> None:
        result.candidates.extend(resp.candidates)
        result.errors.extend(resp.errors)
        if resp.degraded:
            result.degraded = True
            result.assumptions.append(
                f"数据源 {provider_name} 返回降级结果，部分信息可能不完整。"
            )

    @staticmethod
    def _record_failure(
        result: OrchestratorResult,
        provider_name: str,
        code: ProviderErrorCode,
        message: str,
    ) -> None:
        result.degraded = True
        result.errors.append(
            ProviderError(
                code=code,
                message=message,
                provider_name=provider_name,
                retryable=code == ProviderErrorCode.TIMEOUT,
                degraded=True,
            )
        )
        result.assumptions.append(
            f"数据源 {provider_name} 调用失败（{code.value}），相关推荐基于 AI 知识生成。"
        )
        logger.warning("Provider %s failed: [%s] %s", provider_name, code.value, message)

    @staticmethod
    def _dedup(candidates: list[ProviderCandidate]) -> list[ProviderCandidate]:
        """Deduplicate by candidate_id, keeping the first (higher-priority) occurrence."""
        seen: set[str] = set()
        out: list[ProviderCandidate] = []
        for c in candidates:
            if c.candidate_id not in seen:
                seen.add(c.candidate_id)
                out.append(c)
        return out
