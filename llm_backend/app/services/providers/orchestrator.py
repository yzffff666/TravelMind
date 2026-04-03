from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

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

    When a provider fails the orchestrator catches the exception,
    records a ``ProviderError``, marks the result as *degraded*,
    and appends a human-readable assumption string so downstream
    nodes can surface it in ``validation.assumptions``.
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
        """Run search + map recall within the call budget."""
        result = OrchestratorResult()

        if self._policy.is_enabled(ProviderType.SEARCH):
            for sp in self._registry.search_providers:
                if result.calls_made >= self._policy.max_calls_per_request:
                    result.assumptions.append(
                        "已达到单次请求调用上限，部分搜索源未调用。"
                    )
                    break
                await self._call_search(sp, query, context, result)

        if self._policy.is_enabled(ProviderType.MAP):
            kw = keywords or [query]
            for mp in self._registry.map_providers:
                if result.calls_made >= self._policy.max_calls_per_request:
                    result.assumptions.append(
                        "已达到单次请求调用上限，部分地图源未调用。"
                    )
                    break
                await self._call_map(mp, city, kw, context, result)

        if not result.candidates:
            result.degraded = True
            result.assumptions.append(
                "所有数据源均不可用或无匹配结果，行程基于 AI 知识生成，实际信息请自行核实。"
            )

        result.candidates = self._dedup(result.candidates)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_search(
        self,
        provider: SearchProvider,
        query: str,
        context: ProviderCallContext | None,
        result: OrchestratorResult,
    ) -> None:
        result.calls_made += 1
        try:
            resp = await asyncio.wait_for(
                provider.search(
                    query=query,
                    top_k=self._policy.top_k_search,
                    context=context,
                ),
                timeout=self._policy.timeout_seconds,
            )
            self._merge_response(resp, result, provider.name)
        except asyncio.TimeoutError:
            self._record_failure(result, provider.name, ProviderErrorCode.TIMEOUT, "搜索服务超时")
        except Exception as exc:  # noqa: BLE001
            self._record_failure(result, provider.name, ProviderErrorCode.UNKNOWN, str(exc))

    async def _call_map(
        self,
        provider: MapProvider,
        city: str,
        keywords: list[str],
        context: ProviderCallContext | None,
        result: OrchestratorResult,
    ) -> None:
        result.calls_made += 1
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
            self._merge_response(resp, result, provider.name)
        except asyncio.TimeoutError:
            self._record_failure(result, provider.name, ProviderErrorCode.TIMEOUT, "地图服务超时")
        except Exception as exc:  # noqa: BLE001
            self._record_failure(result, provider.name, ProviderErrorCode.UNKNOWN, str(exc))

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
