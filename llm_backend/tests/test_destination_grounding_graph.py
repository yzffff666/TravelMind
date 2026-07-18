import asyncio
import json
from unittest.mock import patch

from app.domain.travel.query_processor import TravelQueryProcessor
from app.services.constraint_filter import ConstraintFilter
from app.services.destination_grounding import DestinationProfile, DestinationResolver
from app.services.evidence_builder import EvidenceBuilder
from app.services.providers.base import ProviderCandidate
from app.services.ranking_scorer import RankingScorer
from app.services.recall_service import RecallResult


def _run(coro):
    return asyncio.run(coro)


class _DunhuangLookup:
    name = "fixture_geocoder"

    async def lookup(self, destination: str):
        if destination != "敦煌":
            return None
        return DestinationProfile(
            requested_name=destination,
            canonical_name="敦煌",
            country="中国",
            center_lat=40.1421,
            center_lng=94.6619,
            radius_km=45,
            confidence=0.92,
            source=self.name,
            is_dynamic=True,
        )


class _FixtureRecall:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = 0

    async def recall_from_qp(self, qp_output):
        self.calls += 1
        return RecallResult(
            candidates=list(self.candidates),
            city=qp_output["constraints"]["destination_city"],
            recall_query=qp_output.get("recall_query", "敦煌 景点"),
        )


class _FixtureLLM:
    def __init__(self, places):
        self.places = places
        self.calls = 0

    async def astream(self, messages):
        self.calls += 1
        days = [
            {
                "day_index": index,
                "slots": [
                    {"slot": "上午", "activity": f"游览{self.places[0]}", "place": self.places[0]},
                    {"slot": "下午", "activity": f"游览{self.places[1]}", "place": self.places[1]},
                    {"slot": "晚上", "activity": f"游览{self.places[2]}", "place": self.places[2]},
                ],
            }
            for index in range(1, 4)
        ]
        yield type("Chunk", (), {"content": json.dumps({"days": days, "budget_summary": {"total_estimate": 5000}})})()


def _candidate(title, *, lat, lng, city):
    return ProviderCandidate(
        candidate_id=f"fixture-{title}",
        source="fixture_map",
        title=title,
        snippet=f"{title} 本地景点",
        score=0.9,
        tags=["文化", "景点"],
        extra={
            "lat": lat,
            "lng": lng,
            "city": city,
            "address": f"{city}{title}",
            "rating": 4.7,
            "photos": ["https://example.com/photo.jpg"],
        },
    )


def _pipeline(recall):
    return (
        TravelQueryProcessor(enable_structured_qp=False),
        recall,
        RankingScorer(),
        ConstraintFilter(),
        EvidenceBuilder(),
        None,
    )


def test_dynamic_grounding_filters_cross_city_candidate_before_draft_generation():
    import app.lg_agent.travel_draft_graph as tdg

    local_places = ["莫高窟", "敦煌博物馆", "鸣沙山月牙泉"]
    recall = _FixtureRecall([
        _candidate(local_places[0], lat=40.1424, lng=94.6615, city="敦煌市"),
        _candidate(local_places[1], lat=40.1340, lng=94.6620, city="敦煌市"),
        _candidate(local_places[2], lat=40.0885, lng=94.6811, city="敦煌市"),
        _candidate("东京塔", lat=35.6586, lng=139.7454, city="Tokyo"),
    ])
    llm = _FixtureLLM(local_places)
    resolver = DestinationResolver(lookups=[_DunhuangLookup()])

    with patch.object(tdg, "_get_pipeline", return_value=_pipeline(recall)), patch.object(
        tdg, "_get_destination_resolver", return_value=resolver
    ), patch.object(tdg, "_get_llm", return_value=llm):
        result = _run(tdg.travel_draft_graph.ainvoke({"query": "帮我规划敦煌3天，预算5000"}))

    assert llm.calls == 1
    assert result["grounding_status"] == "grounded"
    assert result["final_itinerary"] is not None
    assert "东京塔" not in [candidate.candidate.title for candidate in result["pipeline_result"].candidates]
    output_places = {
        slot["place"]
        for day in result["final_itinerary"]["days"]
        for slot in day["slots"]
    }
    assert output_places <= set(local_places)


def test_dynamic_grounding_stops_before_llm_when_verified_candidates_are_insufficient():
    import app.lg_agent.travel_draft_graph as tdg

    recall = _FixtureRecall([
        _candidate("莫高窟", lat=40.1424, lng=94.6615, city="敦煌市"),
        _candidate("敦煌博物馆", lat=40.1340, lng=94.6620, city="敦煌市"),
        _candidate("东京塔", lat=35.6586, lng=139.7454, city="Tokyo"),
    ])
    llm = _FixtureLLM(["莫高窟", "敦煌博物馆", "东京塔"])
    resolver = DestinationResolver(lookups=[_DunhuangLookup()])

    with patch.object(tdg, "_get_pipeline", return_value=_pipeline(recall)), patch.object(
        tdg, "_get_destination_resolver", return_value=resolver
    ), patch.object(tdg, "_get_llm", return_value=llm):
        result = _run(tdg.travel_draft_graph.ainvoke({"query": "帮我规划敦煌3天，预算5000"}))

    assert result["grounding_status"] == "insufficient_candidates"
    assert result["final_itinerary"] is None
    assert "可验证的本地景点" in result["final_text"]
    assert llm.calls == 0


def test_dynamic_grounding_planner_replaces_llm_hallucinated_place_with_verified_candidate():
    import app.lg_agent.travel_draft_graph as tdg

    local_places = ["莫高窟", "敦煌博物馆", "鸣沙山月牙泉"]
    recall = _FixtureRecall([
        _candidate(local_places[0], lat=40.1424, lng=94.6615, city="敦煌市"),
        _candidate(local_places[1], lat=40.1340, lng=94.6620, city="敦煌市"),
        _candidate(local_places[2], lat=40.0885, lng=94.6811, city="敦煌市"),
    ])
    llm = _FixtureLLM(["莫高窟", "东京塔", "鸣沙山月牙泉"])
    resolver = DestinationResolver(lookups=[_DunhuangLookup()])

    with patch.object(tdg, "_get_pipeline", return_value=_pipeline(recall)), patch.object(
        tdg, "_get_destination_resolver", return_value=resolver
    ), patch.object(tdg, "_get_llm", return_value=llm):
        result = _run(tdg.travel_draft_graph.ainvoke({"query": "帮我规划敦煌3天，预算5000"}))

    assert llm.calls == 1
    assert result["final_itinerary"] is not None
    places = [
        slot["place"]
        for day in result["final_itinerary"]["days"]
        for slot in day["slots"]
    ]
    assert set(places) == set(local_places)
    assert "东京塔" not in places
