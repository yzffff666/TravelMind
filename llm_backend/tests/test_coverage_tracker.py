"""Tests for T-M2-004: Evidence coverage tracker.

Covers:
- Basic coverage computation (full, partial, zero)
- Primary POI selection (place > activity fallback)
- Per-slot detail breakdown
- Target threshold check (design.md DoD >= 80%)
- Aggregate statistics across multiple requests
- compute_from_dict with valid and invalid input
-口径稳定性: same input → same output
- Edge cases (single slot, empty evidence, multi-day)
"""

import pytest
from pydantic import ValidationError

from app.schemas.itinerary_v1 import ItineraryV1
from app.services.coverage_tracker import (
    AggregateCoverageReport,
    CoverageReport,
    CoverageTracker,
    SlotCoverageDetail,
    TARGET_COVERAGE,
)


def _build_itinerary(
    days_spec: list[list[dict]],
    evidence: list | None = None,
) -> ItineraryV1:
    """Build a minimal ItineraryV1 from a slot spec.

    days_spec: list of days, each day is a list of slot dicts with keys:
        slot, activity, place (optional), evidence_refs (optional)
    """
    days = []
    for i, slots_data in enumerate(days_spec, start=1):
        slots = []
        for s in slots_data:
            slots.append({
                "slot": s.get("slot", "morning"),
                "activity": s["activity"],
                "place": s.get("place"),
                "evidence_refs": s.get("evidence_refs", []),
            })
        days.append({"day_index": i, "slots": slots})

    return ItineraryV1(
        schema_version="itinerary.v1",
        itinerary_id="test-001",
        revision_id="rev-001",
        trip_profile={"destination_city": "上海"},
        days=days,
        budget_summary={"total_estimate": 5000},
        evidence=evidence or [],
    )


# ======================== Basic Coverage ========================


class TestBasicCoverage:
    def test_full_coverage(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "外滩", "place": "外滩", "evidence_refs": ["ev-1"]},
            {"slot": "afternoon", "activity": "东方明珠", "place": "东方明珠", "evidence_refs": ["ev-2"]},
        ]])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.coverage_score == 1.0
        assert report.total_slots == 2
        assert report.covered_slots == 2
        assert report.meets_target is True

    def test_partial_coverage(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "外滩", "evidence_refs": ["ev-1"]},
            {"slot": "afternoon", "activity": "东方明珠", "evidence_refs": []},
        ]])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.coverage_score == 0.5
        assert report.covered_slots == 1
        assert report.total_slots == 2

    def test_zero_coverage(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "自由活动"},
            {"slot": "afternoon", "activity": "休息"},
        ]])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.coverage_score == 0.0
        assert report.covered_slots == 0
        assert report.meets_target is False

    def test_multi_day_coverage(self):
        it = _build_itinerary([
            [
                {"slot": "morning", "activity": "外滩", "evidence_refs": ["ev-1"]},
                {"slot": "afternoon", "activity": "豫园", "evidence_refs": ["ev-2"]},
            ],
            [
                {"slot": "morning", "activity": "迪士尼", "evidence_refs": ["ev-3"]},
                {"slot": "afternoon", "activity": "自由活动"},
            ],
        ])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.total_slots == 4
        assert report.covered_slots == 3
        assert report.coverage_score == 0.75


# ======================== Primary POI Selection ========================


class TestPrimaryPOI:
    def test_place_is_primary_when_present(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "游览", "place": "外滩"},
        ]])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.details[0].primary_poi == "外滩"

    def test_activity_fallback_when_no_place(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "自由活动"},
        ]])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.details[0].primary_poi == "自由活动"


# ======================== Detail Breakdown ========================


class TestDetailBreakdown:
    def test_detail_fields(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "外滩", "place": "外滩",
             "evidence_refs": ["ev-1", "ev-2"]},
        ]])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        d = report.details[0]
        assert isinstance(d, SlotCoverageDetail)
        assert d.day_index == 1
        assert d.slot_name == "morning"
        assert d.primary_poi == "外滩"
        assert d.has_evidence is True
        assert d.evidence_ref_count == 2

    def test_detail_per_slot(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "A", "evidence_refs": ["ev-1"]},
            {"slot": "afternoon", "activity": "B"},
        ]])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert len(report.details) == 2
        assert report.details[0].has_evidence is True
        assert report.details[1].has_evidence is False


# ======================== Target Threshold ========================


class TestTargetThreshold:
    def test_default_target_is_80_percent(self):
        assert TARGET_COVERAGE == 0.80

    def test_meets_target_at_80(self):
        slots = [
            {"slot": f"s{i}", "activity": f"POI{i}", "evidence_refs": ["ev"]}
            for i in range(4)
        ] + [{"slot": "s4", "activity": "POI4"}]
        it = _build_itinerary([slots])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.coverage_score == 0.8
        assert report.meets_target is True

    def test_below_target(self):
        slots = [
            {"slot": "s0", "activity": "A", "evidence_refs": ["ev"]},
            {"slot": "s1", "activity": "B"},
            {"slot": "s2", "activity": "C"},
        ]
        it = _build_itinerary([slots])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.coverage_score < 0.80
        assert report.meets_target is False

    def test_custom_target(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "A", "evidence_refs": ["ev"]},
            {"slot": "afternoon", "activity": "B"},
        ]])
        tracker = CoverageTracker(target=0.50)
        report = tracker.compute(it)

        assert report.meets_target is True


# ======================== Aggregate ========================


class TestAggregate:
    def test_basic_aggregate(self):
        tracker = CoverageTracker()

        it1 = _build_itinerary([[
            {"slot": "m", "activity": "A", "evidence_refs": ["ev"]},
        ]])
        it2 = _build_itinerary([[
            {"slot": "m", "activity": "A", "evidence_refs": ["ev"]},
            {"slot": "a", "activity": "B"},
        ]])

        r1 = tracker.compute(it1)
        r2 = tracker.compute(it2)
        agg = tracker.aggregate([r1, r2])

        assert agg.total_requests == 2
        assert agg.avg_coverage == 0.75
        assert agg.min_coverage == 0.5
        assert agg.max_coverage == 1.0

    def test_aggregate_target_hit_rate(self):
        tracker = CoverageTracker()

        full = _build_itinerary([[
            {"slot": "m", "activity": "A", "evidence_refs": ["ev"]},
        ]])
        empty = _build_itinerary([[
            {"slot": "m", "activity": "A"},
        ]])

        reports = [tracker.compute(full), tracker.compute(empty)]
        agg = tracker.aggregate(reports)

        assert agg.requests_meeting_target == 1
        assert agg.target_hit_rate == 0.5

    def test_aggregate_empty(self):
        tracker = CoverageTracker()
        agg = tracker.aggregate([])

        assert agg.total_requests == 0
        assert agg.avg_coverage == 0.0

    def test_aggregate_skips_invalid(self):
        tracker = CoverageTracker()
        empty_report = CoverageReport()
        valid = tracker.compute(_build_itinerary([[
            {"slot": "m", "activity": "A", "evidence_refs": ["ev"]},
        ]]))
        agg = tracker.aggregate([empty_report, valid])

        assert agg.total_requests == 1
        assert agg.avg_coverage == 1.0


# ======================== compute_from_dict ========================


class TestComputeFromDict:
    def test_valid_dict(self):
        tracker = CoverageTracker()
        d = {
            "schema_version": "itinerary.v1",
            "itinerary_id": "t1",
            "revision_id": "r1",
            "trip_profile": {"destination_city": "上海"},
            "days": [{"day_index": 1, "slots": [
                {"slot": "morning", "activity": "外滩", "evidence_refs": ["ev-1"]},
            ]}],
            "budget_summary": {"total_estimate": 5000},
        }
        report = tracker.compute_from_dict(d)

        assert report.coverage_score == 1.0
        assert report.total_slots == 1

    def test_invalid_dict_returns_empty(self):
        tracker = CoverageTracker()
        report = tracker.compute_from_dict({"invalid": True})

        assert report.total_slots == 0
        assert report.coverage_score == 0.0


# ======================== 口径稳定性 ========================


class TestStability:
    def test_same_input_same_output(self):
        it = _build_itinerary([
            [
                {"slot": "morning", "activity": "外滩", "evidence_refs": ["ev-1"]},
                {"slot": "afternoon", "activity": "豫园"},
            ],
            [
                {"slot": "morning", "activity": "迪士尼", "evidence_refs": ["ev-2"]},
            ],
        ])
        tracker = CoverageTracker()
        r1 = tracker.compute(it)
        r2 = tracker.compute(it)

        assert r1.coverage_score == r2.coverage_score
        assert r1.total_slots == r2.total_slots
        assert r1.covered_slots == r2.covered_slots
        assert r1.meets_target == r2.meets_target

    def test_deterministic_detail_order(self):
        it = _build_itinerary([
            [{"slot": "morning", "activity": "A"}, {"slot": "afternoon", "activity": "B"}],
            [{"slot": "evening", "activity": "C"}],
        ])
        tracker = CoverageTracker()
        r1 = tracker.compute(it)
        r2 = tracker.compute(it)

        for d1, d2 in zip(r1.details, r2.details):
            assert d1.day_index == d2.day_index
            assert d1.slot_name == d2.slot_name
            assert d1.primary_poi == d2.primary_poi


# ======================== Edge Cases ========================


class TestEdgeCases:
    def test_single_slot_covered(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "唯一", "evidence_refs": ["ev"]},
        ]])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.coverage_score == 1.0
        assert report.total_slots == 1

    def test_multiple_evidence_refs_still_one_covered(self):
        it = _build_itinerary([[
            {"slot": "morning", "activity": "外滩",
             "evidence_refs": ["ev-1", "ev-2", "ev-3"]},
        ]])
        tracker = CoverageTracker()
        report = tracker.compute(it)

        assert report.covered_slots == 1
        assert report.details[0].evidence_ref_count == 3

    def test_report_structure(self):
        report = CoverageReport()
        assert hasattr(report, "coverage_score")
        assert hasattr(report, "total_slots")
        assert hasattr(report, "covered_slots")
        assert hasattr(report, "meets_target")
        assert hasattr(report, "details")

    def test_aggregate_report_structure(self):
        agg = AggregateCoverageReport()
        assert hasattr(agg, "total_requests")
        assert hasattr(agg, "avg_coverage")
        assert hasattr(agg, "min_coverage")
        assert hasattr(agg, "max_coverage")
        assert hasattr(agg, "requests_meeting_target")
        assert hasattr(agg, "target_hit_rate")
