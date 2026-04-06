"""Evidence coverage tracker — per-slot POI coverage statistics.

Implements T-M2-004: 证据覆盖率统计口径实现

Design reference: ``design.md`` §6.1

Coverage specification (verbatim from design.md):
- 覆盖对象：``slot`` 主 POI（非所有候选 POI）。
- 公式：有有效 ``evidence_refs`` 的主 POI 数 / 全部主 POI 数。
- 统计范围：仅对成功生成 ``final_itinerary`` 的请求统计。
- DoD 目标：>= 80%（design.md M2 DoD）。

The "主 POI" of a slot is ``slot.place`` when present, otherwise
``slot.activity`` (every slot has an activity by schema constraint).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.itinerary_v1 import ItineraryV1


TARGET_COVERAGE = 0.80


@dataclass(slots=True)
class SlotCoverageDetail:
    """Per-slot coverage detail for debugging and reporting."""

    day_index: int
    slot_name: str
    primary_poi: str
    has_evidence: bool
    evidence_ref_count: int


@dataclass(slots=True)
class CoverageReport:
    """Coverage result for a single ``final_itinerary``.

    Attributes
    ----------
    coverage_score : fraction in [0, 1]
    total_slots : number of slots analysed
    covered_slots : number of slots with valid evidence_refs
    meets_target : True if coverage_score >= TARGET_COVERAGE
    details : per-slot breakdown
    """

    coverage_score: float = 0.0
    total_slots: int = 0
    covered_slots: int = 0
    meets_target: bool = False
    details: list[SlotCoverageDetail] = field(default_factory=list)


@dataclass
class AggregateCoverageReport:
    """Coverage aggregated across multiple ``final_itinerary`` requests.

    Only successful requests (those that produced a valid ItineraryV1)
    contribute to the aggregate — per design.md specification.
    """

    total_requests: int = 0
    avg_coverage: float = 0.0
    min_coverage: float = 1.0
    max_coverage: float = 0.0
    requests_meeting_target: int = 0
    target_hit_rate: float = 0.0


class CoverageTracker:
    """Stateless tracker that computes evidence coverage for itineraries.

    Usage::

        tracker = CoverageTracker()
        report = tracker.compute(itinerary_v1)
        print(report.coverage_score)  # e.g. 0.75

    For aggregate statistics across multiple requests::

        tracker = CoverageTracker()
        reports = [tracker.compute(it) for it in successful_itineraries]
        agg = tracker.aggregate(reports)
        print(agg.avg_coverage)  # e.g. 0.82
    """

    def __init__(self, target: float = TARGET_COVERAGE) -> None:
        self._target = target

    def compute(self, itinerary: ItineraryV1) -> CoverageReport:
        """Compute per-slot evidence coverage for a single itinerary.

        Parameters
        ----------
        itinerary : a successfully generated ``ItineraryV1`` instance.

        Returns
        -------
        CoverageReport with score, counts, and per-slot detail.
        """
        details: list[SlotCoverageDetail] = []

        for day in itinerary.days:
            for slot in day.slots:
                primary_poi = slot.place or slot.activity
                has_evidence = bool(slot.evidence_refs)

                details.append(SlotCoverageDetail(
                    day_index=day.day_index,
                    slot_name=slot.slot,
                    primary_poi=primary_poi,
                    has_evidence=has_evidence,
                    evidence_ref_count=len(slot.evidence_refs),
                ))

        total = len(details)
        covered = sum(1 for d in details if d.has_evidence)
        score = covered / total if total > 0 else 0.0

        return CoverageReport(
            coverage_score=round(score, 4),
            total_slots=total,
            covered_slots=covered,
            meets_target=score >= self._target,
            details=details,
        )

    def compute_from_dict(self, itinerary_dict: dict[str, Any]) -> CoverageReport:
        """Convenience: compute from a raw dict (e.g. from JSON response).

        Validates the dict as ``ItineraryV1`` first. If validation fails,
        returns an empty report (coverage = 0, total_slots = 0) because
        failed itineraries are excluded from statistics per design.md.
        """
        try:
            itinerary = ItineraryV1(**itinerary_dict)
        except Exception:
            return CoverageReport()
        return self.compute(itinerary)

    def aggregate(self, reports: list[CoverageReport]) -> AggregateCoverageReport:
        """Aggregate coverage across multiple successful requests.

        Parameters
        ----------
        reports : list of ``CoverageReport`` from ``compute()``.
                  Only reports with ``total_slots > 0`` are counted
                  (zero-slot reports indicate failed/invalid itineraries).
        """
        valid = [r for r in reports if r.total_slots > 0]

        if not valid:
            return AggregateCoverageReport()

        scores = [r.coverage_score for r in valid]
        meeting = sum(1 for r in valid if r.meets_target)

        return AggregateCoverageReport(
            total_requests=len(valid),
            avg_coverage=round(sum(scores) / len(scores), 4),
            min_coverage=round(min(scores), 4),
            max_coverage=round(max(scores), 4),
            requests_meeting_target=meeting,
            target_hit_rate=round(meeting / len(valid), 4),
        )
