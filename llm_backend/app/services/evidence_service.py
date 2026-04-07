"""Evidence v1 structure, attribution rules, and degradation logic.

Implements T-M2-003: Evidence field standardization + source attribution.

Design reference: ``docs/下层能力流水线技术方案.md`` §4.5

Responsibilities:
- Map ``ProviderCandidate`` / ``ScoredCandidate`` → ``EvidenceItem``
- Generate attribution text per provider source
- Track degradation when P1 evidence fields are missing
- Link ``evidence_refs`` from slot POI names to evidence IDs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.schemas.itinerary_v1 import EvidenceItem, P1_MISSING_ASSUMPTIONS
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import ScoredCandidate

ATTRIBUTION_TEMPLATES: dict[str, str] = {
    "amap_search": "数据来源：高德地图搜索",
    "amap_map": "数据来源：高德地图 POI",
    "serp_search": "数据来源：Google 搜索（via SerpAPI）",
    "serp_map": "数据来源：Google Maps（via SerpAPI）",
    "mock_search": "数据来源：本地测试数据",
    "mock_map": "数据来源：本地测试数据",
}

DEFAULT_ATTRIBUTION = "数据来源：外部搜索"

_SOURCE_TYPE_MAP: dict[str, str] = {
    "amap_search": "search",
    "serp_search": "search",
    "mock_search": "search",
    "amap_map": "map",
    "serp_map": "map",
    "mock_map": "map",
}

_SNIPPET_MAX_LEN = 300


@dataclass(slots=True)
class EvidenceDegradation:
    """Tracks which evidence fields are missing and what assumptions to add."""

    missing_fields: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


class EvidenceFactory:
    """Converts provider candidates into standardized ``EvidenceItem`` instances.

    Usage::

        factory = EvidenceFactory()
        items, assumptions = factory.build_many(scored_candidates)
        refs = factory.link_evidence_refs(items, "外滩")
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_one(
        self,
        candidate: ProviderCandidate,
        *,
        evidence_id: str | None = None,
    ) -> tuple[EvidenceItem, EvidenceDegradation]:
        """Build a single ``EvidenceItem`` from a ``ProviderCandidate``."""
        eid = evidence_id or self._make_evidence_id(candidate)

        provider = candidate.source or None
        url = candidate.extra.get("url") or None
        snippet = candidate.snippet[:_SNIPPET_MAX_LEN] if candidate.snippet else None
        fetched_at = datetime.now(timezone.utc).isoformat()
        attribution = self._make_attribution(candidate.source)
        source_type = _SOURCE_TYPE_MAP.get(candidate.source or "")

        rating = candidate.extra.get("rating")
        cost_est = candidate.extra.get("cost_estimate")

        confidence = self._compute_confidence(candidate, url)

        item = EvidenceItem(
            evidence_id=eid,
            provider=provider,
            source_type=source_type,
            title=candidate.title or None,
            url=url,
            snippet=snippet,
            fetched_at=fetched_at,
            attribution=attribution,
            confidence=confidence,
            rating=float(rating) if rating is not None else None,
            cost_estimate=float(cost_est) if cost_est is not None else None,
        )

        degradation = self._check_degradation(item)
        return item, degradation

    def build_many(
        self,
        candidates: list[ProviderCandidate] | list[ScoredCandidate],
    ) -> tuple[list[EvidenceItem], list[str]]:
        """Build evidence list, deduplicating by evidence_id.

        Returns ``(items, deduplicated_assumptions)``.
        """
        items: list[EvidenceItem] = []
        all_assumptions: list[str] = []
        seen_ids: set[str] = set()

        for c in candidates:
            candidate = c.candidate if isinstance(c, ScoredCandidate) else c

            eid = self._make_evidence_id(candidate)
            if eid in seen_ids:
                continue
            seen_ids.add(eid)

            item, deg = self.build_one(candidate, evidence_id=eid)
            items.append(item)
            all_assumptions.extend(deg.assumptions)

        return items, list(dict.fromkeys(all_assumptions))

    @staticmethod
    def link_evidence_refs(
        evidence_items: list[EvidenceItem],
        slot_poi_name: str,
    ) -> list[str]:
        """Find ``evidence_id`` values matching a slot's POI name.

        Uses bidirectional substring matching to handle cases where:
        - LLM outputs "外滩风景区" but evidence title is "外滩"
        - LLM outputs "大熊猫基地" but evidence title is "成都大熊猫繁育研究基地"
        """
        if not slot_poi_name:
            return []

        refs: list[str] = []
        name_lower = slot_poi_name.lower()
        for item in evidence_items:
            title_lower = item.title.lower() if item.title else ""
            if title_lower and (name_lower in title_lower or title_lower in name_lower):
                refs.append(item.evidence_id)
            elif name_lower in item.evidence_id.lower():
                refs.append(item.evidence_id)
        return refs

    @staticmethod
    def compute_coverage(
        evidence_items: list[EvidenceItem],
        slot_poi_names: list[str],
    ) -> float:
        """Fraction of slot POI names that have at least one evidence link.

        This provides a quick coverage metric without needing the full
        ``T-M2-004`` statistics pipeline.
        """
        if not slot_poi_names:
            return 0.0

        titles_lower = {
            item.title.lower() for item in evidence_items if item.title
        }
        eids_lower = {item.evidence_id.lower() for item in evidence_items}

        covered = 0
        for name in slot_poi_names:
            nl = name.lower()
            if any(nl in t for t in titles_lower) or any(nl in e for e in eids_lower):
                covered += 1

        return covered / len(slot_poi_names)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_evidence_id(candidate: ProviderCandidate) -> str:
        return f"ev-{candidate.candidate_id}"

    @staticmethod
    def _make_attribution(source: str | None) -> str:
        if not source:
            return DEFAULT_ATTRIBUTION
        return ATTRIBUTION_TEMPLATES.get(source, DEFAULT_ATTRIBUTION)

    @staticmethod
    def _compute_confidence(
        candidate: ProviderCandidate,
        url: str | None,
    ) -> float:
        """Heuristic confidence in [0, 1] based on field completeness."""
        score = 0.0
        if candidate.title:
            score += 0.2
        if candidate.snippet:
            score += 0.2
        if url:
            score += 0.2
        if candidate.extra.get("rating"):
            score += 0.2
        if candidate.extra.get("address"):
            score += 0.1
        if candidate.extra.get("cost_estimate"):
            score += 0.1
        return min(round(score, 2), 1.0)

    @staticmethod
    def _check_degradation(item: EvidenceItem) -> EvidenceDegradation:
        deg = EvidenceDegradation()
        if not item.provider:
            deg.missing_fields.append("evidence.provider")
            deg.assumptions.append(
                P1_MISSING_ASSUMPTIONS["evidence.provider"]
            )
        if not item.url:
            deg.missing_fields.append("evidence.url")
            deg.assumptions.append(
                P1_MISSING_ASSUMPTIONS["evidence.url"]
            )
        if not item.fetched_at:
            deg.missing_fields.append("evidence.fetched_at")
            deg.assumptions.append(
                P1_MISSING_ASSUMPTIONS["evidence.fetched_at"]
            )
        return deg
