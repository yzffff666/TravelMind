from __future__ import annotations

import copy
import uuid

import pytest

from app.services.day_replan_service import DayReplanService
from app.services.destination_grounding import DestinationProfile, DestinationResolver
from app.services.providers.base import ProviderCandidate
from app.services.recall_service import RecallResult


def _make_itinerary() -> dict:
    return {
        "schema_version": "itinerary.v1",
        "itinerary_id": str(uuid.uuid4()),
        "revision_id": "rev-old-001",
        "base_revision_id": None,
        "trip_profile": {
            "destination_city": "上海",
            "constraints": {
                "budget_range": "约 6000 元",
                "traveler_type": "朋友",
                "preferences": ["文化", "美食"],
            },
        },
        "days": [
            {
                "day_index": i,
                "theme": f"第{i}天主题",
                "slots": [
                    {"slot": "上午", "activity": f"Day{i} 上午活动", "place": f"景点A{i}", "transit": "步行"},
                    {"slot": "下午", "activity": f"Day{i} 下午活动", "place": f"景点B{i}", "transit": "地铁"},
                    {"slot": "晚上", "activity": f"Day{i} 晚上活动", "place": f"餐厅C{i}", "transit": "打车"},
                ],
            }
            for i in range(1, 4)
        ],
        "budget_summary": {
            "total_estimate": 6000,
            "by_category": {"transport": 1000, "hotel": 2000, "tickets": 500, "food": 2000, "other": 500},
        },
        "validation": {"assumptions": []},
    }


class _FakeRecall:
    def __init__(self, candidates: list[ProviderCandidate]) -> None:
        self.candidates = candidates
        self.last_query = ""

    async def recall_simple(self, *, query: str, city: str, preferences=None, context=None) -> RecallResult:
        self.last_query = query
        return RecallResult(
            candidates=self.candidates,
            assumptions=["fake recall"],
            city=city,
            recall_query=query,
            calls_made=1,
        )


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


def _candidate(
    title: str,
    *,
    rating: float = 4.7,
    lat: float = 31.2304,
    lng: float = 121.4737,
    tags: list[str] | None = None,
    snippet: str | None = None,
) -> ProviderCandidate:
    return ProviderCandidate(
        candidate_id=f"{title}-上海",
        source="fake",
        title=title,
        snippet=snippet if snippet is not None else f"{title} 适合室内文化体验",
        score=rating / 5,
        tags=tags or ["上海", "室内", "文化", "博物馆"],
        extra={
            "address": f"{title}地址",
            "rating": rating,
            "cost_estimate": 80,
            "lat": lat,
            "lng": lng,
            "photos": [f"https://example.com/{title}.jpg"],
        },
    )


@pytest.mark.asyncio
async def test_day_replan_uses_ranked_candidates_for_target_day_only():
    itinerary = _make_itinerary()
    original_day1 = copy.deepcopy(itinerary["days"][0])
    original_day3 = copy.deepcopy(itinerary["days"][2])
    recall = _FakeRecall([
        _candidate("上海博物馆", rating=4.8),
        _candidate("上海当代艺术博物馆", rating=4.6),
        _candidate("K11购物艺术中心", rating=4.5),
    ])
    service = DayReplanService(recall_service=recall)

    report = await service.replan_days(
        itinerary,
        [{"day_index": 2, "constraints": ["indoor"], "raw_request": "把第二天改成室内"}],
    )

    assert report.applied_days == [2]
    assert report.candidate_counts[2] == 3
    assert "上海" in recall.last_query
    assert "室内" in recall.last_query
    assert itinerary["days"][0] == original_day1
    assert itinerary["days"][2] == original_day3

    day2 = itinerary["days"][1]
    assert day2["theme"] == "候选驱动的室内体验"
    assert {slot["place"] for slot in day2["slots"]} == {
        "上海博物馆",
        "上海当代艺术博物馆",
        "K11购物艺术中心",
    }
    assert all(slot["activity"] != "室内" for slot in day2["slots"])
    assert all(slot["evidence_refs"] for slot in day2["slots"])
    assert all(slot.get("location") for slot in day2["slots"])
    assert all(slot.get("image_url") for slot in day2["slots"])


@pytest.mark.asyncio
async def test_day_replan_keeps_existing_day_when_candidates_are_insufficient():
    itinerary = _make_itinerary()
    original_day2 = copy.deepcopy(itinerary["days"][1])
    recall = _FakeRecall([_candidate("上海博物馆")])
    service = DayReplanService(recall_service=recall, min_candidates=2)

    report = await service.replan_days(
        itinerary,
        [{"day_index": 2, "constraints": ["indoor"], "raw_request": "把第二天改成室内"}],
    )

    assert report.applied_days == []
    assert report.candidate_counts[2] == 1
    assert itinerary["days"][1] == original_day2
    assert any("候选不足" in assumption for assumption in report.assumptions)


@pytest.mark.asyncio
async def test_day_replan_replaces_only_requested_slot_with_verified_candidate():
    itinerary = _make_itinerary()
    original_day2 = copy.deepcopy(itinerary["days"][1])
    recall = _FakeRecall([_candidate("上海图书馆", rating=4.8)])
    service = DayReplanService(recall_service=recall)

    report = await service.replan_days(
        itinerary,
        [{
            "day_index": 2,
            "target_slot": "下午",
            "constraints": ["indoor"],
            "raw_request": "把第二天下午改成室内",
        }],
    )

    assert report.applied_days == [2]
    assert report.candidate_counts[2] == 1
    assert "下午时段" in report.diff_items[0]
    day2 = itinerary["days"][1]
    assert day2["theme"] == original_day2["theme"]
    assert day2["slots"][0] == original_day2["slots"][0]
    assert day2["slots"][2] == original_day2["slots"][2]
    assert day2["slots"][1]["slot"] == "下午"
    assert day2["slots"][1]["place"] == "上海图书馆"
    assert day2["slots"][1]["activity"] != "把第二天下午改成室内"
    assert day2["slots"][1]["evidence_refs"]
    assert day2["slots"][1]["location"]


@pytest.mark.asyncio
async def test_target_slot_replan_keeps_original_day_when_no_candidate_is_verified():
    itinerary = _make_itinerary()
    original_day2 = copy.deepcopy(itinerary["days"][1])
    service = DayReplanService(recall_service=_FakeRecall([]))

    report = await service.replan_days(
        itinerary,
        [{
            "day_index": 2,
            "target_slot": "下午",
            "constraints": ["indoor"],
            "raw_request": "把第二天下午改成室内",
        }],
    )

    assert report.applied_days == []
    assert report.candidate_counts[2] == 0
    assert itinerary["days"][1] == original_day2
    assert any("候选不足" in assumption for assumption in report.assumptions)


@pytest.mark.asyncio
async def test_day_replan_prefers_compact_candidates_near_anchor():
    itinerary = _make_itinerary()
    recall = _FakeRecall([
        _candidate("远郊高分公园", rating=5.0, lat=31.3787, lng=121.3183),
        _candidate("上海博物馆", rating=4.6, lat=31.231, lng=121.474),
        _candidate("新天地", rating=4.5, lat=31.2195, lng=121.475),
        _candidate("田子坊", rating=4.4, lat=31.2106, lng=121.468),
    ])
    service = DayReplanService(recall_service=recall)

    report = await service.replan_days(
        itinerary,
        [{
            "day_index": 2,
            "constraints": ["relaxed"],
            "raw_request": "把第二天改轻松一点",
            "anchor_locations": [
                {"lat": 31.231, "lng": 121.474},
                {"lat": 31.2195, "lng": 121.475},
            ],
        }],
    )

    assert report.applied_days == [2]
    day2 = itinerary["days"][1]
    places = [slot["place"] for slot in day2["slots"]]
    assert "远郊高分公园" not in places
    assert set(places) == {"上海博物馆", "新天地", "田子坊"}


@pytest.mark.asyncio
async def test_day_replan_filters_low_quality_sub_poi_titles():
    itinerary = _make_itinerary()
    recall = _FakeRecall([
        _candidate("人民公园-相亲角", rating=5.0),
        _candidate("中华艺术宫-问询台", rating=4.9),
        _candidate("上海博物馆", rating=4.6),
        _candidate("新天地", rating=4.5),
        _candidate("田子坊", rating=4.4),
    ])
    service = DayReplanService(recall_service=recall)

    report = await service.replan_days(
        itinerary,
        [{"day_index": 2, "constraints": ["relaxed"], "raw_request": "把第二天改轻松一点"}],
    )

    assert report.applied_days == [2]
    places = [slot["place"] for slot in itinerary["days"][1]["slots"]]
    assert "人民公园-相亲角" not in places
    assert "中华艺术宫-问询台" not in places
    assert set(places) == {"上海博物馆", "新天地", "田子坊"}


@pytest.mark.asyncio
async def test_indoor_replan_requires_indoor_candidate_relevance():
    itinerary = _make_itinerary()
    recall = _FakeRecall([
        _candidate("外滩", rating=5.0, tags=["地标", "夜景"], snippet="上海黄浦江边户外地标"),
        _candidate("南京路步行街", rating=4.9, tags=["步行街", "美食"], snippet="上海户外商业步行街"),
        _candidate("上海博物馆", rating=4.6),
        _candidate("上海当代艺术博物馆", rating=4.5),
        _candidate("K11购物艺术中心", rating=4.4, tags=["购物中心", "艺术中心"]),
    ])
    service = DayReplanService(recall_service=recall)

    report = await service.replan_days(
        itinerary,
        [{"day_index": 2, "constraints": ["indoor"], "raw_request": "把第二天改成室内"}],
    )

    assert report.applied_days == [2]
    places = [slot["place"] for slot in itinerary["days"][1]["slots"]]
    assert "外滩" not in places
    assert "南京路步行街" not in places
    assert set(places) == {"上海博物馆", "上海当代艺术博物馆", "K11购物艺术中心"}


@pytest.mark.asyncio
async def test_day_replan_for_unseen_city_filters_cross_city_candidates_before_selection():
    itinerary = _make_itinerary()
    itinerary["trip_profile"]["destination_city"] = "敦煌"
    original_day1 = copy.deepcopy(itinerary["days"][0])
    original_day3 = copy.deepcopy(itinerary["days"][2])
    recall = _FakeRecall([
        _candidate("莫高窟", lat=40.1424, lng=94.6615, tags=["敦煌", "文化", "室内", "博物馆"]),
        _candidate("敦煌博物馆", lat=40.1340, lng=94.6620, tags=["敦煌", "文化", "室内", "博物馆"]),
        _candidate("敦煌市图书馆", lat=40.1380, lng=94.6700, tags=["敦煌", "文化", "室内", "图书馆"]),
        _candidate("东京塔", lat=35.6586, lng=139.7454, tags=["东京", "夜景"]),
    ])
    for candidate in recall.candidates[:3]:
        candidate.extra["city"] = "敦煌市"
    recall.candidates[-1].extra["city"] = "Tokyo"
    resolver = DestinationResolver(lookups=[_DunhuangLookup()])
    service = DayReplanService(recall_service=recall, destination_resolver=resolver)

    report = await service.replan_days(
        itinerary,
        [{"day_index": 2, "constraints": ["indoor"], "raw_request": "把第二天改成室内"}],
    )

    assert report.applied_days == [2]
    assert report.grounding_statuses == {2: "grounded"}
    assert report.candidate_counts[2] == 3
    assert {slot["place"] for slot in itinerary["days"][1]["slots"]} == {
        "莫高窟",
        "敦煌博物馆",
        "敦煌市图书馆",
    }
    assert itinerary["days"][0] == original_day1
    assert itinerary["days"][2] == original_day3


@pytest.mark.asyncio
async def test_day_replan_uses_shared_planner_to_avoid_pois_locked_on_other_days():
    itinerary = _make_itinerary()
    itinerary["days"][0]["slots"][0]["place"] = "上海博物馆"
    original_day1 = copy.deepcopy(itinerary["days"][0])
    recall = _FakeRecall([
        _candidate("上海博物馆", rating=5.0),
        _candidate("上海当代艺术博物馆", rating=4.8),
        _candidate("K11购物艺术中心", rating=4.7),
        _candidate("上海图书馆", rating=4.6),
    ])
    service = DayReplanService(recall_service=recall)

    report = await service.replan_days(
        itinerary,
        [{"day_index": 2, "constraints": ["indoor"], "raw_request": "把第二天改成室内"}],
    )

    day2_places = {slot["place"] for slot in itinerary["days"][1]["slots"]}
    assert report.applied_days == [2]
    assert report.planner_statuses == {2: "planned"}
    assert "上海博物馆" not in day2_places
    assert day2_places == {"上海当代艺术博物馆", "K11购物艺术中心", "上海图书馆"}
    assert itinerary["days"][0] == original_day1
