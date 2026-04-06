"""Tests for T-M2-003: Evidence v1 structure, attribution, and degradation.

Covers:
- EvidenceItem schema (new fields: source_type, confidence, rating, cost_estimate)
- EvidenceFactory.build_one — field mapping from ProviderCandidate
- EvidenceFactory.build_many — deduplication and assumption aggregation
- Attribution rules per provider source
- Degradation tracking (P1 field missing → assumption generated)
- Evidence ref linking (slot POI name → evidence_id)
- Coverage metric
- Edge cases (empty input, missing fields, unknown source)
"""

from app.schemas.itinerary_v1 import EvidenceItem, P1_MISSING_ASSUMPTIONS
from app.services.evidence_service import (
    ATTRIBUTION_TEMPLATES,
    DEFAULT_ATTRIBUTION,
    EvidenceDegradation,
    EvidenceFactory,
)
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import ScoredCandidate


def _make_candidate(
    title: str = "外滩",
    source: str = "amap_search",
    snippet: str = "上海标志性建筑群",
    url: str | None = "https://example.com/bund",
    rating: float | None = 4.8,
    cost: float | None = 0.0,
    address: str | None = "上海市黄浦区",
    tags: list[str] | None = None,
) -> ProviderCandidate:
    extra: dict = {}
    if url is not None:
        extra["url"] = url
    if rating is not None:
        extra["rating"] = rating
    if cost is not None:
        extra["cost_estimate"] = cost
    if address is not None:
        extra["address"] = address
    return ProviderCandidate(
        candidate_id=f"{title}-上海",
        source=source,
        title=title,
        snippet=snippet,
        tags=tags or ["地标"],
        extra=extra,
    )


# ======================== Schema Enhancement ========================


class TestEvidenceItemSchema:
    def test_new_fields_accepted(self):
        item = EvidenceItem(
            evidence_id="ev-1",
            source_type="search",
            confidence=0.85,
            rating=4.5,
            cost_estimate=100.0,
        )
        assert item.source_type == "search"
        assert item.confidence == 0.85
        assert item.rating == 4.5
        assert item.cost_estimate == 100.0

    def test_source_type_validation(self):
        for st in ("search", "map", "weather", "review", "manual"):
            item = EvidenceItem(evidence_id="ev-x", source_type=st)
            assert item.source_type == st

    def test_confidence_bounds(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EvidenceItem(evidence_id="ev-x", confidence=1.5)
        with pytest.raises(ValidationError):
            EvidenceItem(evidence_id="ev-x", confidence=-0.1)

    def test_optional_fields_default_none(self):
        item = EvidenceItem(evidence_id="ev-basic")
        assert item.source_type is None
        assert item.confidence is None
        assert item.rating is None
        assert item.cost_estimate is None
        assert item.provider is None
        assert item.url is None

    def test_backward_compatible_with_existing_tests(self):
        item = EvidenceItem(
            evidence_id="ev-compat",
            provider="old_provider",
            title="Test",
            url="https://example.com",
            snippet="test snippet",
            fetched_at="2025-01-01T00:00:00Z",
            attribution="Test source",
        )
        assert item.evidence_id == "ev-compat"
        assert item.provider == "old_provider"


# ======================== EvidenceFactory.build_one ========================


class TestBuildOne:
    def test_basic_mapping(self):
        factory = EvidenceFactory()
        candidate = _make_candidate()
        item, deg = factory.build_one(candidate)

        assert item.evidence_id == "ev-外滩-上海"
        assert item.provider == "amap_search"
        assert item.source_type == "search"
        assert item.title == "外滩"
        assert item.url == "https://example.com/bund"
        assert item.snippet == "上海标志性建筑群"
        assert item.fetched_at is not None
        assert item.attribution == "数据来源：高德地图搜索"
        assert item.rating == 4.8
        assert item.cost_estimate == 0.0

    def test_confidence_computed(self):
        factory = EvidenceFactory()
        full = _make_candidate()
        item, _ = factory.build_one(full)
        assert item.confidence is not None
        assert item.confidence > 0.5

    def test_confidence_low_when_sparse(self):
        factory = EvidenceFactory()
        sparse = _make_candidate(
            snippet="", url=None, rating=None, cost=None, address=None
        )
        item, _ = factory.build_one(sparse)
        assert item.confidence is not None
        assert item.confidence <= 0.3

    def test_custom_evidence_id(self):
        factory = EvidenceFactory()
        item, _ = factory.build_one(_make_candidate(), evidence_id="custom-ev-001")
        assert item.evidence_id == "custom-ev-001"

    def test_snippet_truncated(self):
        factory = EvidenceFactory()
        long_snippet = "很长的" * 200
        c = _make_candidate(snippet=long_snippet)
        item, _ = factory.build_one(c)
        assert len(item.snippet) <= 300

    def test_serp_search_attribution(self):
        factory = EvidenceFactory()
        c = _make_candidate(source="serp_search")
        item, _ = factory.build_one(c)
        assert item.attribution == ATTRIBUTION_TEMPLATES["serp_search"]
        assert item.source_type == "search"

    def test_serp_map_attribution(self):
        factory = EvidenceFactory()
        c = _make_candidate(source="serp_map")
        item, _ = factory.build_one(c)
        assert item.attribution == ATTRIBUTION_TEMPLATES["serp_map"]
        assert item.source_type == "map"

    def test_mock_search_attribution(self):
        factory = EvidenceFactory()
        c = _make_candidate(source="mock_search")
        item, _ = factory.build_one(c)
        assert "本地测试" in item.attribution

    def test_unknown_source_default_attribution(self):
        factory = EvidenceFactory()
        c = _make_candidate(source="unknown_provider")
        item, _ = factory.build_one(c)
        assert item.attribution == DEFAULT_ATTRIBUTION
        assert item.source_type is None


# ======================== Degradation ========================


class TestDegradation:
    def test_full_evidence_no_degradation(self):
        factory = EvidenceFactory()
        c = _make_candidate()
        _, deg = factory.build_one(c)
        assert len(deg.missing_fields) == 0
        assert len(deg.assumptions) == 0

    def test_missing_url_triggers_assumption(self):
        factory = EvidenceFactory()
        c = _make_candidate(url=None)
        _, deg = factory.build_one(c)
        assert "evidence.url" in deg.missing_fields
        assert P1_MISSING_ASSUMPTIONS["evidence.url"] in deg.assumptions

    def test_missing_provider_triggers_assumption(self):
        factory = EvidenceFactory()
        c = ProviderCandidate(
            candidate_id="no-source",
            source="",
            title="Test",
            extra={},
        )
        _, deg = factory.build_one(c)
        assert "evidence.provider" in deg.missing_fields

    def test_degradation_structure(self):
        deg = EvidenceDegradation()
        assert isinstance(deg.missing_fields, list)
        assert isinstance(deg.assumptions, list)


# ======================== EvidenceFactory.build_many ========================


class TestBuildMany:
    def test_basic_build_many(self):
        factory = EvidenceFactory()
        candidates = [
            _make_candidate("外滩"),
            _make_candidate("东方明珠", url="https://example.com/pearl"),
        ]
        items, assumptions = factory.build_many(candidates)
        assert len(items) == 2
        assert items[0].evidence_id != items[1].evidence_id

    def test_deduplication(self):
        factory = EvidenceFactory()
        same = _make_candidate("外滩")
        items, _ = factory.build_many([same, same])
        assert len(items) == 1

    def test_assumptions_deduplicated(self):
        factory = EvidenceFactory()
        c1 = _make_candidate("A", url=None)
        c2 = _make_candidate("B", url=None)
        _, assumptions = factory.build_many([c1, c2])
        url_assumptions = [
            a for a in assumptions
            if "URL" in a or "url" in a.lower()
        ]
        assert len(url_assumptions) == 1

    def test_accepts_scored_candidates(self):
        factory = EvidenceFactory()
        sc = ScoredCandidate(
            candidate=_make_candidate("外滩"),
            total_score=0.85,
            breakdown={"preference_match": 0.9},
        )
        items, _ = factory.build_many([sc])
        assert len(items) == 1
        assert items[0].title == "外滩"

    def test_mixed_candidate_types(self):
        factory = EvidenceFactory()
        raw = _make_candidate("A")
        scored = ScoredCandidate(
            candidate=_make_candidate("B"),
            total_score=0.5,
            breakdown={},
        )
        items, _ = factory.build_many([raw, scored])
        assert len(items) == 2

    def test_empty_input(self):
        factory = EvidenceFactory()
        items, assumptions = factory.build_many([])
        assert items == []
        assert assumptions == []


# ======================== Evidence Ref Linking ========================


class TestLinkEvidenceRefs:
    def test_exact_title_match(self):
        items = [
            EvidenceItem(evidence_id="ev-外滩-上海", title="外滩"),
            EvidenceItem(evidence_id="ev-东方明珠-上海", title="东方明珠"),
        ]
        refs = EvidenceFactory.link_evidence_refs(items, "外滩")
        assert "ev-外滩-上海" in refs
        assert "ev-东方明珠-上海" not in refs

    def test_partial_title_match(self):
        items = [
            EvidenceItem(evidence_id="ev-1", title="上海迪士尼乐园"),
        ]
        refs = EvidenceFactory.link_evidence_refs(items, "迪士尼")
        assert "ev-1" in refs

    def test_fallback_to_evidence_id(self):
        items = [
            EvidenceItem(evidence_id="ev-外滩-上海", title=None),
        ]
        refs = EvidenceFactory.link_evidence_refs(items, "外滩")
        assert "ev-外滩-上海" in refs

    def test_no_match(self):
        items = [
            EvidenceItem(evidence_id="ev-1", title="故宫"),
        ]
        refs = EvidenceFactory.link_evidence_refs(items, "长城")
        assert refs == []

    def test_empty_poi_name(self):
        items = [EvidenceItem(evidence_id="ev-1", title="Test")]
        refs = EvidenceFactory.link_evidence_refs(items, "")
        assert refs == []

    def test_case_insensitive(self):
        items = [
            EvidenceItem(evidence_id="ev-1", title="The Bund"),
        ]
        refs = EvidenceFactory.link_evidence_refs(items, "the bund")
        assert "ev-1" in refs


# ======================== Coverage ========================


class TestCoverage:
    def test_full_coverage(self):
        items = [
            EvidenceItem(evidence_id="ev-1", title="外滩"),
            EvidenceItem(evidence_id="ev-2", title="东方明珠"),
        ]
        cov = EvidenceFactory.compute_coverage(items, ["外滩", "东方明珠"])
        assert cov == 1.0

    def test_partial_coverage(self):
        items = [
            EvidenceItem(evidence_id="ev-1", title="外滩"),
        ]
        cov = EvidenceFactory.compute_coverage(items, ["外滩", "东方明珠"])
        assert cov == 0.5

    def test_zero_coverage(self):
        items = [
            EvidenceItem(evidence_id="ev-1", title="故宫"),
        ]
        cov = EvidenceFactory.compute_coverage(items, ["外滩"])
        assert cov == 0.0

    def test_empty_slots(self):
        items = [EvidenceItem(evidence_id="ev-1", title="A")]
        assert EvidenceFactory.compute_coverage(items, []) == 0.0

    def test_empty_evidence(self):
        assert EvidenceFactory.compute_coverage([], ["A"]) == 0.0
