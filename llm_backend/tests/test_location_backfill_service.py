import asyncio

from app.schemas.itinerary_v1 import BudgetSummary, ItineraryDay, ItinerarySlot, ItineraryV1, TripProfile
from app.services.location_backfill_service import LocationBackfillService, _cache
from app.services.providers.base import ProviderCandidate, ProviderResponse


class FakeMapProvider:
    name = "fake_map"

    async def nearby_poi(self, *, city, keywords, top_k=20, context=None):
        keyword = keywords[0] if keywords else ""
        if keyword == "Karon Beach":
            return ProviderResponse(candidates=[
                ProviderCandidate(
                    candidate_id="karon-wrong",
                    source=self.name,
                    title="Karon Beach",
                    snippet="错误跨区域候选",
                    extra={"lat": 43.948993, "lng": 125.535557, "address": "中国吉林省长春市"},
                ),
                ProviderCandidate(
                    candidate_id="karon-right",
                    source=self.name,
                    title="Karon Beach",
                    snippet="普吉卡伦海滩",
                    extra={"lat": 7.8472, "lng": 98.2931, "address": "Karon, Phuket"},
                ),
            ])
        if keyword != "上海外灘悦榕莊":
            return ProviderResponse()
        return ProviderResponse(candidates=[
            ProviderCandidate(
                candidate_id="banyan-waitan",
                source=self.name,
                title="上海外灘悦榕莊",
                snippet="外滩附近酒店",
                extra={"lat": 31.241, "lng": 121.491, "address": "上海市黄浦区外滩"},
            )
        ])


def _service_with_fake_provider() -> LocationBackfillService:
    svc = LocationBackfillService.__new__(LocationBackfillService)
    svc._providers = [FakeMapProvider()]
    svc._max_slots_per_request = 12
    svc._max_variants_per_place = 4
    svc._provider_timeout_seconds = 1.0
    svc._total_budget_seconds = 5.0
    svc._min_match_score = 0.72
    return svc


def test_backfill_strips_year_prefix_for_poi_match():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-backfill",
        revision_id="rev-backfill",
        trip_profile=TripProfile(destination_city="上海"),
        days=[ItineraryDay(
            day_index=1,
            slots=[ItinerarySlot(slot="下午", activity="休闲", place="2026上海外灘悦榕莊")],
        )],
        budget_summary=BudgetSummary(total_estimate=6000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_itinerary(itinerary))

    slot = itinerary.days[0].slots[0]
    assert report.filled == 1
    assert slot.location is not None
    assert slot.evidence_refs == ["ev-banyan-waitan"]
    assert "地图展示稳定性已提升" in report.assumptions[0]
    assert "海外地点展示稳定性" not in report.assumptions[0]


def test_backfill_rejects_cross_region_overseas_candidate():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-phuket",
        revision_id="rev-phuket",
        trip_profile=TripProfile(destination_city="普吉岛"),
        days=[ItineraryDay(
            day_index=1,
            slots=[ItinerarySlot(slot="上午", activity="海滩散步", place="卡伦海滩")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_itinerary(itinerary))

    slot = itinerary.days[0].slots[0]
    assert report.filled == 1
    assert slot.location is not None
    assert slot.location.lat == 7.8472
    assert slot.location.lng == 98.2931
    assert slot.evidence_refs == ["ev-karon-right"]


def test_backfill_changed_days_only_updates_changed_slots():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-edit",
        revision_id="rev-edit",
        trip_profile=TripProfile(destination_city="上海"),
        days=[
            ItineraryDay(
                day_index=1,
                slots=[ItinerarySlot(slot="上午", activity="休闲", place="2026上海外灘悦榕莊")],
            ),
            ItineraryDay(
                day_index=2,
                slots=[ItinerarySlot(slot="下午", activity="休闲", place="2026上海外灘悦榕莊")],
            ),
        ],
        budget_summary=BudgetSummary(total_estimate=6000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_changed_days(itinerary, [2]))

    day1_slot = itinerary.days[0].slots[0]
    day2_slot = itinerary.days[1].slots[0]
    assert report.filled == 1
    assert day1_slot.location is None
    assert day1_slot.evidence_refs == []
    assert day2_slot.location is not None
    assert day2_slot.evidence_refs == ["ev-banyan-waitan"]
