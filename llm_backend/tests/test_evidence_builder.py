"""Tests for T-M2-000e: EvidenceBuilder pipeline stage.

Covers:
- build() basic mapping from FilterResult to PipelineResult
- Evidence items generated and mapped correctly
- Assumption aggregation from recall + filter + evidence
- Degradation flag propagation
- Slot ↔ evidence linking
- Validation helpers (assumptions + conflicts)
- Edge cases (empty accepted, no recall result)
"""

from app.schemas.itinerary_v1 import EvidenceItem
from app.services.constraint_filter import FilteredCandidate, FilterResult
from app.services.evidence_builder import EvidenceBuilder, PipelineResult
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import ScoredCandidate
from app.services.recall_service import RecallResult


def _make_scored(
    title: str = "外滩",
    source: str = "mock_search",
    cost: float = 0.0,
    url: str | None = "https://example.com",
    rating: float = 4.5,
    total_score: float = 0.8,
) -> ScoredCandidate:
    extra = {"cost_estimate": cost, "rating": rating}
    if url:
        extra["url"] = url
    c = ProviderCandidate(
        candidate_id=f"{title}-上海",
        source=source,
        title=title,
        snippet=f"{title}的描述",
        tags=["景点"],
        extra=extra,
    )
    return ScoredCandidate(candidate=c, total_score=total_score, breakdown={})


def _make_filter_result(
    accepted: list[ScoredCandidate] | None = None,
    rejected: list[FilteredCandidate] | None = None,
    assumptions: list[str] | None = None,
    relaxed: bool = False,
) -> FilterResult:
    return FilterResult(
        accepted=accepted or [],
        rejected=rejected or [],
        assumptions=assumptions or [],
        relaxed=relaxed,
    )


def _make_recall_result(
    city: str = "上海",
    degraded: bool = False,
    assumptions: list[str] | None = None,
) -> RecallResult:
    return RecallResult(
        city=city,
        degraded=degraded,
        assumptions=assumptions or [],
    )


# ======================== Basic Build ========================


class TestBuild:
    def test_basic_build(self):
        sc = _make_scored("外滩")
        fr = _make_filter_result(accepted=[sc])
        rr = _make_recall_result()

        builder = EvidenceBuilder()
        result = builder.build(fr, rr)

        assert isinstance(result, PipelineResult)
        assert len(result.candidates) == 1
        assert len(result.evidence) == 1
        assert result.evidence[0].title == "外滩"
        assert result.evidence[0].provider == "mock_search"
        assert result.recall_city == "上海"

    def test_evidence_map_populated(self):
        sc = _make_scored("外滩")
        fr = _make_filter_result(accepted=[sc])
        builder = EvidenceBuilder()
        result = builder.build(fr)

        assert "外滩-上海" in result.evidence_map
        assert result.evidence_map["外滩-上海"] == "ev-外滩-上海"

    def test_multiple_candidates(self):
        sc1 = _make_scored("外滩", total_score=0.9)
        sc2 = _make_scored("东方明珠", total_score=0.8)
        fr = _make_filter_result(accepted=[sc1, sc2])
        builder = EvidenceBuilder()
        result = builder.build(fr)

        assert len(result.evidence) == 2
        titles = {e.title for e in result.evidence}
        assert "外滩" in titles
        assert "东方明珠" in titles

    def test_coverage_computed(self):
        sc = _make_scored("外滩")
        fr = _make_filter_result(accepted=[sc])
        builder = EvidenceBuilder()
        result = builder.build(fr)

        assert result.coverage == 1.0


# ======================== Assumption Aggregation ========================


class TestAssumptionAggregation:
    def test_recall_assumptions_included(self):
        fr = _make_filter_result(accepted=[_make_scored()])
        rr = _make_recall_result(assumptions=["召回降级：部分数据不可用"])
        builder = EvidenceBuilder()
        result = builder.build(fr, rr)

        assert "召回降级：部分数据不可用" in result.assumptions

    def test_filter_assumptions_included(self):
        fr = _make_filter_result(
            accepted=[_make_scored()],
            assumptions=["过滤后仅剩 2 个候选"],
        )
        builder = EvidenceBuilder()
        result = builder.build(fr)

        assert any("过滤" in a for a in result.assumptions)

    def test_evidence_degradation_assumptions(self):
        sc = _make_scored("无链接", url=None)
        fr = _make_filter_result(accepted=[sc])
        builder = EvidenceBuilder()
        result = builder.build(fr)

        assert any("URL" in a for a in result.assumptions)

    def test_assumptions_deduplicated(self):
        sc1 = _make_scored("A", url=None)
        sc2 = _make_scored("B", url=None)
        fr = _make_filter_result(accepted=[sc1, sc2])
        builder = EvidenceBuilder()
        result = builder.build(fr)

        url_assumptions = [a for a in result.assumptions if "URL" in a]
        assert len(url_assumptions) == 1

    def test_all_stages_merged(self):
        sc = _make_scored("X", url=None)
        fr = _make_filter_result(
            accepted=[sc],
            assumptions=["过滤放宽"],
        )
        rr = _make_recall_result(assumptions=["召回降级"])
        builder = EvidenceBuilder()
        result = builder.build(fr, rr)

        assert len(result.assumptions) >= 3


# ======================== Degradation Flag ========================


class TestDegradation:
    def test_degraded_when_recall_degraded(self):
        fr = _make_filter_result(accepted=[_make_scored()])
        rr = _make_recall_result(degraded=True)
        builder = EvidenceBuilder()
        result = builder.build(fr, rr)

        assert result.degraded is True

    def test_degraded_when_filter_relaxed(self):
        fr = _make_filter_result(
            accepted=[_make_scored()],
            relaxed=True,
            assumptions=["放宽阈值"],
        )
        builder = EvidenceBuilder()
        result = builder.build(fr)

        assert result.degraded is True
        assert result.filter_relaxed is True

    def test_degraded_when_evidence_missing(self):
        sc = _make_scored("无链接", url=None)
        fr = _make_filter_result(accepted=[sc])
        builder = EvidenceBuilder()
        result = builder.build(fr)

        assert result.degraded is True

    def test_not_degraded_when_all_healthy(self):
        sc = _make_scored("完整", url="https://example.com")
        fr = _make_filter_result(accepted=[sc])
        rr = _make_recall_result(degraded=False)
        builder = EvidenceBuilder()
        result = builder.build(fr, rr)

        assert result.degraded is False


# ======================== Slot Linking ========================


class TestSlotLinking:
    def test_link_slot_by_title(self):
        builder = EvidenceBuilder()
        items = [
            EvidenceItem(evidence_id="ev-外滩-上海", title="外滩"),
            EvidenceItem(evidence_id="ev-东方明珠-上海", title="东方明珠"),
        ]
        refs = builder.link_slot(items, "外滩")
        assert "ev-外滩-上海" in refs
        assert "ev-东方明珠-上海" not in refs

    def test_link_slot_partial_match(self):
        builder = EvidenceBuilder()
        items = [EvidenceItem(evidence_id="ev-1", title="上海迪士尼乐园")]
        refs = builder.link_slot(items, "迪士尼")
        assert "ev-1" in refs

    def test_link_slot_no_match(self):
        builder = EvidenceBuilder()
        items = [EvidenceItem(evidence_id="ev-1", title="故宫")]
        refs = builder.link_slot(items, "长城")
        assert refs == []


# ======================== Validation Helpers ========================


class TestValidationHelpers:
    def test_build_validation_assumptions(self):
        fr = _make_filter_result(accepted=[_make_scored()])
        rr = _make_recall_result(assumptions=["测试假设"])
        builder = EvidenceBuilder()
        result = builder.build(fr, rr)

        assumptions = builder.build_validation_assumptions(result)
        assert "测试假设" in assumptions

    def test_build_validation_conflicts(self):
        rejected_sc = _make_scored("贵景点", cost=9999)
        fc = FilteredCandidate(
            scored=rejected_sc,
            rejected=True,
            reject_reasons=["超出预算"],
        )
        fr = _make_filter_result(rejected=[fc])
        builder = EvidenceBuilder()
        conflicts = builder.build_validation_conflicts(fr)

        assert len(conflicts) == 1
        assert "贵景点" in conflicts[0]
        assert "超出预算" in conflicts[0]

    def test_empty_conflicts_when_no_rejections(self):
        fr = _make_filter_result(accepted=[_make_scored()])
        builder = EvidenceBuilder()
        conflicts = builder.build_validation_conflicts(fr)
        assert conflicts == []


# ======================== Edge Cases ========================


class TestEdgeCases:
    def test_empty_accepted(self):
        fr = _make_filter_result(accepted=[])
        builder = EvidenceBuilder()
        result = builder.build(fr)

        assert result.candidates == []
        assert result.evidence == []
        assert result.evidence_map == {}
        assert result.coverage == 0.0

    def test_no_recall_result(self):
        fr = _make_filter_result(accepted=[_make_scored()])
        builder = EvidenceBuilder()
        result = builder.build(fr, recall_result=None)

        assert result.recall_city == ""
        assert len(result.evidence) == 1

    def test_pipeline_result_structure(self):
        result = PipelineResult()
        assert hasattr(result, "candidates")
        assert hasattr(result, "evidence")
        assert hasattr(result, "evidence_map")
        assert hasattr(result, "assumptions")
        assert hasattr(result, "degraded")
        assert hasattr(result, "coverage")
        assert hasattr(result, "filter_relaxed")
        assert hasattr(result, "recall_city")
