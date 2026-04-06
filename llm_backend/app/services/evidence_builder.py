"""Evidence Builder — final stage of the QP → Recall → Ranking → Filter → Evidence pipeline.

Design reference: ``docs/下层能力流水线技术方案.md`` §4.5

Responsibilities:
1. Accept ``FilterResult`` (accepted ``ScoredCandidate`` list) from the filter stage.
2. Convert accepted candidates into standardized ``EvidenceItem`` instances
   via ``EvidenceFactory``.
3. Aggregate assumptions from ALL upstream stages (recall, filter, evidence
   degradation) into a single list for ``ValidationResult``.
4. Provide slot ↔ evidence linking so that ``ItinerarySlot.evidence_refs``
   can be populated when the Draft node builds the final itinerary.
5. Produce a ``PipelineResult`` that contains everything the Draft node needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.itinerary_v1 import EvidenceItem
from app.services.constraint_filter import FilterResult
from app.services.evidence_service import EvidenceFactory
from app.services.ranking_scorer import ScoredCandidate
from app.services.recall_service import RecallResult


@dataclass
class PipelineResult:
    """Complete output of the five-stage pipeline, ready for Draft node consumption.

    Fields
    ------
    candidates : final accepted ``ScoredCandidate`` list (scored + filtered)
    evidence   : ``EvidenceItem`` list mapped from accepted candidates
    evidence_map : ``{candidate_id: evidence_id}`` for slot linking
    assumptions : aggregated from recall → filter → evidence stages
    degraded : True if any upstream stage degraded
    coverage : quick coverage metric (fraction of candidates with evidence)
    filter_relaxed : True if the filter had to relax thresholds
    recall_city : the city recalled for (pass-through for Draft node)
    """

    candidates: list[ScoredCandidate] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    evidence_map: dict[str, str] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    degraded: bool = False
    coverage: float = 0.0
    filter_relaxed: bool = False
    recall_city: str = ""


class EvidenceBuilder:
    """Orchestrates the evidence building stage of the pipeline.

    Usage::

        builder = EvidenceBuilder()
        result = builder.build(
            filter_result=filter_result,
            recall_result=recall_result,
        )

    Or use the convenience method to run from QP output::

        result = builder.build_from_qp(
            filter_result=filter_result,
            recall_result=recall_result,
            qp_output=qp_output,
        )
    """

    def __init__(self, factory: EvidenceFactory | None = None) -> None:
        self._factory = factory or EvidenceFactory()

    def build(
        self,
        filter_result: FilterResult,
        recall_result: RecallResult | None = None,
    ) -> PipelineResult:
        """Build evidence from filter output, aggregating all upstream assumptions."""
        accepted = filter_result.accepted

        evidence_items, evidence_assumptions = self._factory.build_many(accepted)

        evidence_map: dict[str, str] = {}
        for sc in accepted:
            eid = f"ev-{sc.candidate.candidate_id}"
            evidence_map[sc.candidate.candidate_id] = eid

        all_assumptions: list[str] = []
        if recall_result and recall_result.assumptions:
            all_assumptions.extend(recall_result.assumptions)
        if filter_result.assumptions:
            all_assumptions.extend(filter_result.assumptions)
        if evidence_assumptions:
            all_assumptions.extend(evidence_assumptions)
        all_assumptions = list(dict.fromkeys(all_assumptions))

        degraded = bool(
            (recall_result and recall_result.degraded)
            or filter_result.relaxed
            or evidence_assumptions
        )

        poi_names = [sc.candidate.title for sc in accepted if sc.candidate.title]
        coverage = self._factory.compute_coverage(evidence_items, poi_names)

        return PipelineResult(
            candidates=accepted,
            evidence=evidence_items,
            evidence_map=evidence_map,
            assumptions=all_assumptions,
            degraded=degraded,
            coverage=coverage,
            filter_relaxed=filter_result.relaxed,
            recall_city=recall_result.city if recall_result else "",
        )

    def link_slot(
        self,
        evidence_items: list[EvidenceItem],
        slot_poi_name: str,
    ) -> list[str]:
        """Find evidence_ids for a given slot's POI name.

        Delegates to ``EvidenceFactory.link_evidence_refs``.
        This is the method the Draft node calls per slot when
        populating ``ItinerarySlot.evidence_refs``.
        """
        return self._factory.link_evidence_refs(evidence_items, slot_poi_name)

    def build_validation_assumptions(
        self,
        pipeline_result: PipelineResult,
    ) -> list[str]:
        """Return the complete assumption list for ``ValidationResult.assumptions``.

        Includes all degradation notes from the pipeline. The Draft node
        should write these directly into ``ItineraryV1.validation.assumptions``.
        """
        return list(pipeline_result.assumptions)

    def build_validation_conflicts(
        self,
        filter_result: FilterResult,
    ) -> list[str]:
        """Extract reject reasons as conflict entries for ``ValidationResult.conflicts``.

        Each rejected candidate contributes its reject_reasons. The Draft
        node can choose to include these in ``validation.conflicts`` for
        full transparency.
        """
        conflicts: list[str] = []
        for fc in filter_result.rejected:
            for reason in fc.reject_reasons:
                title = fc.scored.candidate.title or fc.scored.candidate.candidate_id
                conflicts.append(f"{title}: {reason}")
        return conflicts
