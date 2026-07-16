from __future__ import annotations

import copy
import uuid

import pytest

from app.services.day_replan_service import DayReplanService
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


def _candidate(title: str, *, rating: float = 4.7) -> ProviderCandidate:
    return ProviderCandidate(
        candidate_id=f"{title}-上海",
        source="fake",
        title=title,
        snippet=f"{title} 适合室内文化体验",
        score=rating / 5,
        tags=["上海", "室内", "文化", "博物馆"],
        extra={
            "address": f"{title}地址",
            "rating": rating,
            "cost_estimate": 80,
            "lat": 31.2304,
            "lng": 121.4737,
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
    assert [slot["place"] for slot in day2["slots"]] == [
        "上海博物馆",
        "上海当代艺术博物馆",
        "K11购物艺术中心",
    ]
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
