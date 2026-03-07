"""
T-M2-012 Patch 编辑引擎最小操作集单测。
- replace_slot / delete_slot / insert_slot / update_constraint
- 局部修改后保持 itinerary schema 可校验
"""
from __future__ import annotations

from app.domain.travel.patch_engine import TravelPatchEngine
from app.schemas.itinerary_v1 import BudgetSummary, ItineraryDay, ItinerarySlot, ItineraryV1, TripProfile


def _sample_itinerary_dict() -> dict:
    itinerary = ItineraryV1(
        itinerary_id="iti-1",
        revision_id="rev-1",
        trip_profile=TripProfile(destination_city="上海"),
        days=[
            ItineraryDay(
                day_index=1,
                slots=[
                    ItinerarySlot(slot="上午", activity="外滩散步"),
                    ItinerarySlot(slot="下午", activity="南京路观光"),
                    ItinerarySlot(slot="晚上", activity="豫园夜景"),
                ],
            ),
            ItineraryDay(
                day_index=2,
                slots=[
                    ItinerarySlot(slot="上午", activity="博物馆"),
                    ItinerarySlot(slot="下午", activity="新天地"),
                    ItinerarySlot(slot="晚上", activity="黄浦江夜游"),
                ],
            ),
        ],
        budget_summary=BudgetSummary(total_estimate=6000),
    )
    return itinerary.model_dump(mode="json")


def test_patch_replace_slot_local_change():
    engine = TravelPatchEngine()
    out = engine.apply_edit_query(
        query="把第2天下午改成上海电影博物馆",
        itinerary=_sample_itinerary_dict(),
    )
    assert out["ok"] is True
    assert out["changed_days"] == [2]
    updated = out["itinerary"]
    assert updated["base_revision_id"] == "rev-1"
    assert updated["revision_id"] != "rev-1"
    day2 = [d for d in updated["days"] if d["day_index"] == 2][0]
    afternoon = [s for s in day2["slots"] if s["slot"] == "下午"][0]
    assert afternoon["activity"] == "上海电影博物馆"
    assert updated["change_summary"]["changed_days"] == [2]


def test_patch_delete_slot_keeps_schema_valid():
    engine = TravelPatchEngine()
    out = engine.apply_edit_query(
        query="删除第1天晚上安排",
        itinerary=_sample_itinerary_dict(),
    )
    assert out["ok"] is True
    day1 = [d for d in out["itinerary"]["days"] if d["day_index"] == 1][0]
    assert len(day1["slots"]) == 2
    assert "晚上" not in [slot["slot"] for slot in day1["slots"]]


def test_patch_insert_slot():
    engine = TravelPatchEngine()
    out = engine.apply_edit_query(
        query="给第1天下午添加静安寺打卡",
        itinerary=_sample_itinerary_dict(),
    )
    assert out["ok"] is True
    day1 = [d for d in out["itinerary"]["days"] if d["day_index"] == 1][0]
    assert len(day1["slots"]) == 4
    assert any(slot["activity"] == "静安寺打卡" for slot in day1["slots"])
    assert out["changed_days"] == [1]


def test_patch_update_budget_constraint():
    engine = TravelPatchEngine()
    out = engine.apply_edit_query(
        query="预算改成5000",
        itinerary=_sample_itinerary_dict(),
    )
    assert out["ok"] is True
    assert out["itinerary"]["budget_summary"]["total_estimate"] == 5000.0
    assert out["itinerary"]["trip_profile"]["constraints"]["budget_range"] == "约5000元"
    assert out["changed_days"] == [1, 2]


def test_patch_requires_day_for_slot_edit():
    engine = TravelPatchEngine()
    out = engine.apply_edit_query(
        query="把下午改成咖啡店休息",
        itinerary=_sample_itinerary_dict(),
    )
    assert out["ok"] is False
    assert "第几天" in out["message"] or "天数" in out["message"]
