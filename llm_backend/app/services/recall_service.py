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

        keywords = list(preferences) if preferences else []

        orch_result: OrchestratorResult = await self._orchestrator.recall(
            query=recall_query or city,
            city=city,
            keywords=keywords if keywords else None,
            context=context,
        )

        return RecallResult(
            candidates=orch_result.candidates,
            assumptions=orch_result.assumptions,
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
            keywords=preferences,
            context=context,
        )
        return RecallResult(
            candidates=orch_result.candidates,
            assumptions=orch_result.assumptions,
            degraded=orch_result.degraded,
            calls_made=orch_result.calls_made,
            city=city,
            recall_query=query,
        )
