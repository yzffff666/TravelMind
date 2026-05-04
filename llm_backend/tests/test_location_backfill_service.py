import asyncio
import time

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


class SlowTrackingMapProvider:
    name = "slow_tracking_map"

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def nearby_poi(self, *, city, keywords, top_k=20, context=None):
        keyword = keywords[0] if keywords else ""
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.05)
        self.active -= 1
        return ProviderResponse(candidates=[
            ProviderCandidate(
                candidate_id=f"poi-{keyword}",
                source=self.name,
                title=keyword,
                snippet=f"{city} {keyword}",
                extra={"lat": 31.2, "lng": 121.4, "address": f"{city} {keyword}"},
            )
        ])


class EmptyTrackingMapProvider:
    name = "empty_tracking_map"

    def __init__(self) -> None:
        self.calls = 0

    async def nearby_poi(self, *, city, keywords, top_k=20, context=None):
        self.calls += 1
        return ProviderResponse()


class BboxOnlyMapProvider:
    name = "bbox_only_map"

    async def nearby_poi(self, *, city, keywords, top_k=20, context=None):
        keyword = keywords[0] if keywords else ""
        return ProviderResponse(candidates=[
            ProviderCandidate(
                candidate_id=f"bbox-{keyword}",
                source=self.name,
                title=keyword,
                snippet="wrong region",
                extra={"lat": 43.948993, "lng": 125.535557, "address": "Changchun"},
            )
        ])


class LowScoreMapProvider:
    name = "low_score_map"

    async def nearby_poi(self, *, city, keywords, top_k=20, context=None):
        return ProviderResponse(candidates=[
            ProviderCandidate(
                candidate_id="low-score",
                source=self.name,
                title="Unrelated Museum",
                snippet="in bounds but weak text match",
                extra={"lat": 7.88, "lng": 98.39, "address": "Phuket"},
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
    svc._max_concurrent_backfills = 4
    return svc


def _service_with_provider(
    provider,
    *,
    max_concurrent_backfills: int = 4,
    max_variants_per_place: int = 2,
) -> LocationBackfillService:
    svc = LocationBackfillService.__new__(LocationBackfillService)
    svc._providers = [provider]
    svc._max_slots_per_request = 12
    svc._max_variants_per_place = max_variants_per_place
    svc._provider_timeout_seconds = 1.0
    svc._total_budget_seconds = 5.0
    svc._min_match_score = 0.72
    svc._max_concurrent_backfills = max_concurrent_backfills
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


def test_backfill_builds_phuket_old_town_aliases():
    svc = _service_with_fake_provider()

    variants = svc._build_variants("普吉老镇", "Phuket")

    assert "Old Phuket Town" in variants
    assert "Phuket Old Town" in variants


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


def test_backfill_runs_with_bounded_concurrency():
    _cache.clear()
    provider = SlowTrackingMapProvider()
    itinerary = ItineraryV1(
        itinerary_id="it-concurrent",
        revision_id="rev-concurrent",
        trip_profile=TripProfile(destination_city="上海"),
        days=[
            ItineraryDay(
                day_index=1,
                slots=[
                    ItinerarySlot(slot="上午", activity="游览", place="地点A"),
                    ItinerarySlot(slot="下午", activity="游览", place="地点B"),
                ],
            ),
            ItineraryDay(
                day_index=2,
                slots=[
                    ItinerarySlot(slot="上午", activity="游览", place="地点C"),
                    ItinerarySlot(slot="下午", activity="游览", place="地点D"),
                ],
            ),
        ],
        budget_summary=BudgetSummary(total_estimate=6000),
    )

    report = asyncio.run(
        _service_with_provider(provider, max_concurrent_backfills=2).backfill_itinerary(itinerary)
    )

    assert provider.max_active == 2
    assert report.attempted == 4
    assert report.filled == 4
    assert all(
        slot.location is not None and slot.evidence_refs
        for day in itinerary.days
        for slot in day.slots
    )


def test_backfill_negative_cache_prevents_repeated_provider_miss():
    _cache.clear()
    provider = EmptyTrackingMapProvider()
    itinerary = ItineraryV1(
        itinerary_id="it-cache-miss",
        revision_id="rev-cache-miss",
        trip_profile=TripProfile(destination_city="Phuket"),
        days=[ItineraryDay(
            day_index=1,
            slots=[
                ItinerarySlot(slot="morning", activity="visit", place="Unknown Place"),
                ItinerarySlot(slot="afternoon", activity="visit", place="Unknown Place"),
            ],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(
        _service_with_provider(
            provider,
            max_concurrent_backfills=1,
            max_variants_per_place=1,
        ).backfill_itinerary(itinerary)
    )

    assert report.filled == 0
    assert report.unresolved == ["Unknown Place", "Unknown Place"]
    assert provider.calls == 1


def test_backfill_diagnostics_distinguish_bbox_and_score_rejections():
    _cache.clear()

    bbox_result = asyncio.run(
        _service_with_provider(BboxOnlyMapProvider())._resolve_place(
            "Karon Beach",
            "Phuket",
            time.perf_counter(),
        )
    )
    _cache.clear()
    score_result = asyncio.run(
        _service_with_provider(LowScoreMapProvider())._resolve_place(
            "Karon Beach",
            "Phuket",
            time.perf_counter(),
        )
    )

    assert bbox_result.resolved is None
    assert bbox_result.diagnostics.fallback_reason == "bbox_rejected"
    assert bbox_result.diagnostics.rejected_bbox_count == 2
    assert bbox_result.diagnostics.best_candidate_title == "Karon Beach"
    assert score_result.resolved is None
    assert score_result.diagnostics.fallback_reason == "score_rejected"
    assert score_result.diagnostics.rejected_score_count == 2
    assert score_result.diagnostics.best_candidate_title == "Unrelated Museum"


def test_backfill_skips_generic_activity_without_provider_call():
    _cache.clear()
    provider = EmptyTrackingMapProvider()
    itinerary = ItineraryV1(
        itinerary_id="it-generic-activity",
        revision_id="rev-generic-activity",
        trip_profile=TripProfile(destination_city="成都"),
        days=[ItineraryDay(
            day_index=2,
            slots=[ItinerarySlot(slot="下午", activity="更轻松的室内活动", place="更轻松的室内活动")],
        )],
        budget_summary=BudgetSummary(total_estimate=6000),
    )

    report = asyncio.run(_service_with_provider(provider).backfill_itinerary(itinerary))

    assert report.attempted == 0
    assert report.filled == 0
    assert report.skipped == 1
    assert report.unresolved == []
    assert provider.calls == 0
    assert itinerary.days[0].slots[0].location is None


def test_backfill_generic_activity_filter_keeps_specific_pois():
    svc = _service_with_fake_provider()

    assert svc._should_skip_generic_activity("更轻松的室内活动")
    assert not svc._should_skip_generic_activity("四川博物院")
    assert not svc._should_skip_generic_activity("九眼桥")
    assert not svc._should_skip_generic_activity("鹤鸣茶社")
