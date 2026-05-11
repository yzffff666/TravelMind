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
        if keyword == "Old Phuket Town":
            return ProviderResponse(candidates=[
                ProviderCandidate(
                    candidate_id="old-phuket-town",
                    source=self.name,
                    title="Old Phuket Town",
                    snippet="Historic old town in Phuket",
                    extra={"lat": 7.884, "lng": 98.389, "address": "Phuket Old Town"},
                ),
            ])
        if keyword == "The Boathouse Restaurant":
            return ProviderResponse(candidates=[
                ProviderCandidate(
                    candidate_id="boathouse-restaurant",
                    source=self.name,
                    title="The Boathouse Restaurant",
                    snippet="Restaurant in Kata Beach, Phuket",
                    extra={"lat": 7.818, "lng": 98.299, "address": "Kata Beach, Phuket"},
                ),
            ])
        if keyword == "Naka Weekend Market":
            return ProviderResponse(candidates=[
                ProviderCandidate(
                    candidate_id="naka-weekend-market",
                    source=self.name,
                    title="Naka Weekend Market",
                    snippet="Weekend night market in Phuket",
                    extra={"lat": 7.880, "lng": 98.366, "address": "Phuket"},
                ),
            ])
        if keyword == "Thanon Talang":
            return ProviderResponse(candidates=[
                ProviderCandidate(
                    candidate_id="thanon-talang",
                    source=self.name,
                    title="Thanon Talang",
                    snippet="Historic street in Phuket Old Town",
                    extra={"lat": 7.8847, "lng": 98.3898, "address": "Talat Yai, Phuket"},
                ),
            ])
        if keyword == "Goh Raja Yai":
            return ProviderResponse(candidates=[
                ProviderCandidate(
                    candidate_id="goh-raja-yai",
                    source=self.name,
                    title="Goh Raja Yai",
                    snippet="Racha Yai island day trip from Phuket",
                    extra={"lat": 7.6038, "lng": 98.3664, "address": "Rawai, Phuket"},
                ),
            ])
        if keyword in {"Phuket Big Buddha", "Big Buddha Temple"}:
            return ProviderResponse(candidates=[
                ProviderCandidate(
                    candidate_id="big-buddha-temple",
                    source=self.name,
                    title="Big Buddha Temple",
                    snippet="Hilltop Buddha temple in Phuket",
                    extra={"lat": 7.8276, "lng": 98.3128, "address": "Karon, Phuket"},
                ),
            ])
        if keyword == "Kan Eang Restaurant":
            return ProviderResponse(candidates=[
                ProviderCandidate(
                    candidate_id="kan-eang-restaurant",
                    source=self.name,
                    title="Kan Eang Restaurant - ร้านกันเอง",
                    snippet="Seafood restaurant near Chalong Pier",
                    extra={"lat": 7.8213, "lng": 98.3389, "address": "Chalong, Phuket"},
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


class CityRecordingMapProvider(FakeMapProvider):
    name = "city_recording_map"

    def __init__(self) -> None:
        self.cities: list[str] = []

    async def nearby_poi(self, *, city, keywords, top_k=20, context=None):
        self.cities.append(city)
        return await super().nearby_poi(city=city, keywords=keywords, top_k=top_k, context=context)


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


class ZeroScoreMapProvider:
    name = "zero_score_map"

    async def nearby_poi(self, *, city, keywords, top_k=20, context=None):
        return ProviderResponse(candidates=[
            ProviderCandidate(
                candidate_id="zero-score",
                source=self.name,
                title="xyz",
                snippet="in bounds but no text overlap",
                extra={"lat": 7.88, "lng": 98.39, "address": "Phuket"},
            )
        ])


class ListAddressMapProvider:
    name = "list_address_map"

    async def nearby_poi(self, *, city, keywords, top_k=20, context=None):
        keyword = keywords[0] if keywords else ""
        return ProviderResponse(candidates=[
            ProviderCandidate(
                candidate_id=f"list-address-{keyword}",
                source=self.name,
                title=keyword,
                snippet="provider returned a structured address",
                extra={"lat": 7.884, "lng": 98.389, "address": ["Phuket", "Old Town"]},
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
    city_variants = svc._build_variants("普吉老城", "Phuket")

    assert "Old Phuket Town" in variants
    assert "Phuket Old Town" in variants
    assert "Old Phuket Town" in city_variants
    assert "Phuket Old Town" in city_variants


def test_backfill_builds_english_phuket_poi_aliases():
    svc = _service_with_fake_provider()

    big_buddha_variants = svc._build_variants("Big Buddha Phuket", "Phuket")
    weekend_market_variants = svc._build_variants("Phuket Weekend Market", "Phuket")
    kan_eang_variants = svc._build_variants("Kan Eang@Pier", "Phuket")
    bangla_variants = svc._build_variants("Bangla Road", "Phuket")
    thalang_variants = svc._build_variants("Thalang Road", "Phuket")
    racha_variants = svc._build_variants("Racha Island", "Phuket")

    assert "Phuket Big Buddha" in big_buddha_variants[:3]
    assert "Big Buddha Temple" in big_buddha_variants
    assert "Naka Weekend Market Phuket" in weekend_market_variants[:3]
    assert "Naka Market Phuket" in weekend_market_variants
    assert "Phuket Weekend Night Market" in weekend_market_variants
    assert "Phuket Indy Night Market" not in weekend_market_variants
    assert "Kan Eang Restaurant" in kan_eang_variants
    assert "Bangla Road Patong" in bangla_variants
    assert "Thanon Talang" in thalang_variants
    assert "Goh Raja Yai" in racha_variants
    assert "Koh Racha Yai" in racha_variants


def test_backfill_resolves_phuket_old_town_via_alias():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-old-town",
        revision_id="rev-old-town",
        trip_profile=TripProfile(destination_city="普吉岛轻松"),
        days=[ItineraryDay(
            day_index=1,
            slots=[ItinerarySlot(slot="上午", activity="普吉老城漫步", place="普吉老城")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_itinerary(itinerary))

    assert report.filled == 1
    assert itinerary.days[0].slots[0].location is not None
    assert itinerary.days[0].slots[0].evidence_refs == ["ev-old-phuket-town"]


def test_backfill_resolves_boathouse_via_alias():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-boathouse",
        revision_id="rev-boathouse",
        trip_profile=TripProfile(destination_city="Phuket"),
        days=[ItineraryDay(
            day_index=2,
            slots=[ItinerarySlot(slot="晚上", activity="海边晚餐", place="The Boathouse Wine & Grill")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_itinerary(itinerary))

    assert report.filled == 1
    assert itinerary.days[0].slots[0].location is not None
    assert itinerary.days[0].slots[0].evidence_refs == ["ev-boathouse-restaurant"]


def test_backfill_resolves_big_buddha_via_english_alias():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-big-buddha",
        revision_id="rev-big-buddha",
        trip_profile=TripProfile(destination_city="Phuket"),
        days=[ItineraryDay(
            day_index=3,
            slots=[ItinerarySlot(slot="morning", activity="Visit the Big Buddha", place="Big Buddha Phuket")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_itinerary(itinerary))

    assert report.filled == 1
    assert itinerary.days[0].slots[0].location is not None
    assert itinerary.days[0].slots[0].evidence_refs == ["ev-big-buddha-temple"]


def test_backfill_resolves_thalang_road_via_romanized_alias():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-thalang-road",
        revision_id="rev-thalang-road",
        trip_profile=TripProfile(destination_city="Phuket"),
        days=[ItineraryDay(
            day_index=1,
            slots=[ItinerarySlot(slot="morning", activity="Walk through Old Town", place="Thalang Road")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_itinerary(itinerary))

    assert report.filled == 1
    assert itinerary.days[0].slots[0].location is not None
    assert itinerary.days[0].slots[0].evidence_refs == ["ev-thanon-talang"]


def test_backfill_resolves_racha_island_via_local_alias():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-racha-island",
        revision_id="rev-racha-island",
        trip_profile=TripProfile(destination_city="Phuket"),
        days=[ItineraryDay(
            day_index=3,
            slots=[ItinerarySlot(slot="morning", activity="Take a boat to Racha Island", place="Racha Island")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_itinerary(itinerary))

    assert report.filled == 1
    assert itinerary.days[0].slots[0].location is not None
    assert itinerary.days[0].slots[0].evidence_refs == ["ev-goh-raja-yai"]


def test_backfill_resolves_kan_eang_via_english_alias():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-kan-eang",
        revision_id="rev-kan-eang",
        trip_profile=TripProfile(destination_city="Phuket"),
        days=[ItineraryDay(
            day_index=1,
            slots=[ItinerarySlot(slot="evening", activity="Seafood dinner", place="Kan Eang@Pier")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_itinerary(itinerary))

    assert report.filled == 1
    assert itinerary.days[0].slots[0].location is not None
    assert itinerary.days[0].slots[0].evidence_refs == ["ev-kan-eang-restaurant"]


def test_backfill_cleans_specific_place_from_generic_alternative():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-naka-market",
        revision_id="rev-naka-market",
        trip_profile=TripProfile(destination_city="普吉岛轻松"),
        days=[ItineraryDay(
            day_index=2,
            slots=[
                ItinerarySlot(
                    slot="晚上",
                    activity="夜市闲逛",
                    place="普吉周末夜市（如当天是周末）或酒店周边",
                )
            ],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_fake_provider().backfill_itinerary(itinerary))

    assert report.filled == 1
    assert itinerary.days[0].slots[0].location is not None
    assert itinerary.days[0].slots[0].evidence_refs == ["ev-naka-weekend-market"]


def test_backfill_place_cleaning_preserves_specific_alternative():
    svc = _service_with_fake_provider()

    assert svc._clean_place_for_backfill("普吉周末夜市（如当天是周末）或酒店周边") == "普吉周末夜市"
    assert svc._clean_place_for_backfill("酒店泳池/附近海滩") == "酒店泳池/附近海滩"
    assert svc._clean_place_for_backfill("Phuket Weekend Market (Naka Market)") == "Phuket Weekend Market"


def test_backfill_normalizes_noisy_destination_before_provider_call():
    _cache.clear()
    provider = CityRecordingMapProvider()
    itinerary = ItineraryV1(
        itinerary_id="it-phuket-relaxed",
        revision_id="rev-phuket-relaxed",
        trip_profile=TripProfile(destination_city="普吉岛轻松"),
        days=[ItineraryDay(
            day_index=1,
            slots=[ItinerarySlot(slot="上午", activity="海滩散步", place="卡伦海滩")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_provider(provider, max_variants_per_place=4).backfill_itinerary(itinerary))

    assert report.filled == 1
    assert provider.cities == ["Phuket", "Phuket"]


def test_backfill_destination_normalization_is_generic():
    svc = _service_with_fake_provider()

    assert svc._normalize_destination("普吉岛轻松") == "Phuket"
    assert svc._normalize_destination("成都亲子三天") == "成都"
    assert svc._normalize_destination("上海 4天 预算6000 情侣") == "上海"
    assert svc._normalize_destination("东京美食游") == "Tokyo"


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


def test_backfill_diagnostics_records_zero_score_candidate_for_audit():
    _cache.clear()

    result = asyncio.run(
        _service_with_provider(ZeroScoreMapProvider(), max_variants_per_place=1)._resolve_place(
            "abc",
            "Phuket",
            time.perf_counter(),
        )
    )

    assert result.resolved is None
    assert result.diagnostics.fallback_reason == "score_rejected"
    assert result.diagnostics.best_candidate_title == "xyz"
    assert result.diagnostics.best_candidate_provider == "zero_score_map"
    assert result.diagnostics.best_candidate_lat == 7.88
    assert result.diagnostics.best_candidate_lng == 98.39
    assert result.diagnostics.best_match_score == 0.0


def test_backfill_budget_exhausted_diagnostics_preserve_planned_variants():
    svc = _service_with_provider(EmptyTrackingMapProvider(), max_variants_per_place=2)

    diagnostics = svc._budget_exhausted_diagnostics("Bangla Road", "Phuket")

    assert diagnostics.fallback_reason == "total_budget_exhausted"
    assert diagnostics.variants_tried == ["Bangla Road", "Bangla Road Patong"]
    assert diagnostics.provider_status_counts == {}
    assert diagnostics.candidate_count == 0
    assert diagnostics.variant_limit_reached is True


def test_backfill_english_token_subset_score_handles_canonical_titles():
    svc = _service_with_fake_provider()

    assert svc._match_score("Big Buddha Phuket", "Big Buddha Temple", "Karon, Phuket") >= 0.8
    assert svc._match_score("Kan Eang@Pier", "Kan Eang Restaurant - ร้านกันเอง", "Chalong, Phuket") >= 0.8


def test_backfill_tolerates_provider_list_address():
    _cache.clear()
    itinerary = ItineraryV1(
        itinerary_id="it-list-address",
        revision_id="rev-list-address",
        trip_profile=TripProfile(destination_city="Phuket"),
        days=[ItineraryDay(
            day_index=1,
            slots=[ItinerarySlot(slot="上午", activity="普吉老城漫步", place="普吉老城")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
    )

    report = asyncio.run(_service_with_provider(ListAddressMapProvider()).backfill_itinerary(itinerary))

    assert report.filled == 1
    assert itinerary.days[0].slots[0].location is not None


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


def test_backfill_skips_generic_relative_place_without_provider_call():
    _cache.clear()
    provider = EmptyTrackingMapProvider()
    itinerary = ItineraryV1(
        itinerary_id="it-relative-place",
        revision_id="rev-relative-place",
        trip_profile=TripProfile(destination_city="Phuket"),
        days=[ItineraryDay(
            day_index=4,
            slots=[ItinerarySlot(slot="上午", activity="放松", place="酒店泳池/附近海滩")],
        )],
        budget_summary=BudgetSummary(total_estimate=12000),
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
    assert svc._should_skip_generic_activity("酒店泳池/附近海滩")
    assert not svc._should_skip_generic_activity("四川博物院")
    assert not svc._should_skip_generic_activity("九眼桥")
    assert not svc._should_skip_generic_activity("鹤鸣茶社")
    assert not svc._should_skip_generic_activity("卡伦海滩")
