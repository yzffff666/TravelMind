"""Recall service: bridges QP output to Provider Orchestrator.

This module is the single entry point for the recall step in the
QP → Recall → Ranking → Filter → Evidence pipeline.

Usage::

    from app.services.recall_service import RecallService

    service = RecallService()
    result = await service.recall_from_qp(qp_output)
    # result.candidates  — deduplicated ProviderCandidate list
    # result.assumptions — degradation notes for downstream
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.providers.base import ProviderCallContext, ProviderCandidate
from app.services.providers.call_policy import ProviderCallPolicy
from app.services.providers.factory import build_registry
from app.services.providers.orchestrator import OrchestratorResult, ProviderOrchestrator

logger = logging.getLogger(__name__)

_BASE_MAP_KEYWORDS = ("景点", "博物馆", "公园")
_PREFERENCE_MAP_KEYWORDS = {
    "亲子": ("亲子景点", "儿童博物馆", "动物园", "科技馆"),
    "文化": ("文化景点", "博物馆", "历史街区"),
    "美食": ("本地美食", "小吃街", "特色餐厅"),
    "海边": ("海滩", "海滨景点", "度假区"),
    "慢旅行": ("公园", "历史街区", "咖啡馆"),
}
_NON_TRAVEL_TERMS = (
    "亲子鉴定",
    "鉴定中心",
    "司法鉴定",
    "珠宝评估",
    "评估师",
    "报社",
    "中国邮政报",
    "旅行社",
    "pdf",
)


@dataclass
class RecallResult:
    """Aggregated recall output consumed by downstream ranking/filtering."""

    candidates: list[ProviderCandidate] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    degraded: bool = False
    calls_made: int = 0
    city: str = ""
    recall_query: str = ""


class RecallService:
    """Stateless service that executes recall given QP output.

    Instantiate once at app startup; call ``recall_from_qp`` per request.
    """

    def __init__(
        self,
        *,
        policy: ProviderCallPolicy | None = None,
        include_mock_fallback: bool = True,
    ) -> None:
        registry = build_registry(include_mock_fallback=include_mock_fallback)
        self._orchestrator = ProviderOrchestrator(
            registry=registry,
            policy=policy or ProviderCallPolicy(),
        )

    async def recall_from_qp(
        self,
        qp_output: dict[str, Any],
        *,
        context: ProviderCallContext | None = None,
    ) -> RecallResult:
        """Run recall using structured QP output.

        Parameters
        ----------
        qp_output:
            The dict returned by ``TravelQueryProcessor.process()``.
            Expected keys: ``recall_query``, ``constraints``
            (with ``destination_city``, ``preferences``).
        context:
            Optional call context for tracing.

        Returns
        -------
        RecallResult with deduplicated candidates and assumptions.
        """
        constraints = qp_output.get("constraints", {})
        city = constraints.get("destination_city", "") or ""
        recall_query = qp_output.get("recall_query", "")
        preferences = constraints.get("preferences", [])

        if not recall_query and not city:
            logger.warning("RecallService: no recall_query or city in QP output")
            return RecallResult(
                degraded=True,
                assumptions=["QP 未提供有效的召回查询或目的地城市，跳过候选召回。"],
            )

        keywords = _map_keywords(preferences)

        orch_result: OrchestratorResult = await self._orchestrator.recall(
            query=recall_query or city,
            city=city,
            keywords=keywords if keywords else None,
            context=context,
        )

        candidates, filter_assumptions = _filter_non_travel_candidates(orch_result.candidates)

        return RecallResult(
            candidates=candidates,
            assumptions=[*orch_result.assumptions, *filter_assumptions],
            degraded=orch_result.degraded,
            calls_made=orch_result.calls_made,
            city=city,
            recall_query=recall_query,
        )

    async def recall_simple(
        self,
        *,
        query: str,
        city: str,
        preferences: list[str] | None = None,
        context: ProviderCallContext | None = None,
    ) -> RecallResult:
        """Convenience method for direct recall without full QP output."""
        orch_result = await self._orchestrator.recall(
            query=query,
            city=city,
            keywords=_map_keywords(preferences or []),
            context=context,
        )
        candidates, filter_assumptions = _filter_non_travel_candidates(orch_result.candidates)
        return RecallResult(
            candidates=candidates,
            assumptions=[*orch_result.assumptions, *filter_assumptions],
            degraded=orch_result.degraded,
            calls_made=orch_result.calls_made,
            city=city,
            recall_query=query,
        )


def _map_keywords(preferences: list[str] | None) -> list[str]:
    """Convert user preferences into POI-oriented map keywords."""
    keywords: list[str] = []
    for pref in preferences or []:
        expanded = _PREFERENCE_MAP_KEYWORDS.get(pref)
        if expanded:
            keywords.extend(expanded)
        elif pref:
            keywords.append(f"{pref}景点")
    keywords.extend(_BASE_MAP_KEYWORDS)
    return list(dict.fromkeys(k for k in keywords if k))


def _filter_non_travel_candidates(
    candidates: list[ProviderCandidate],
) -> tuple[list[ProviderCandidate], list[str]]:
    """Remove common SERP/Maps false positives before ranking."""
    kept: list[ProviderCandidate] = []
    removed: list[str] = []
    for candidate in candidates:
        haystack = " ".join([
            candidate.title or "",
            candidate.snippet or "",
            " ".join(candidate.tags or []),
            str(candidate.extra.get("displayed_link", "")),
            str(candidate.extra.get("url", "")),
        ]).lower()
        if any(term.lower() in haystack for term in _NON_TRAVEL_TERMS):
            removed.append(candidate.title or candidate.candidate_id)
            continue
        kept.append(candidate)

    assumptions = []
    if removed:
        assumptions.append(
            f"已过滤 {len(removed)} 个明显非旅行候选：{', '.join(removed[:3])}。"
        )
    return kept, assumptions
