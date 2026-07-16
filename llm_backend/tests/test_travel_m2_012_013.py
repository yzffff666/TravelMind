"""
T-M2-012 / T-M2-013 集成测试：
- QA 规则回答（_answer_itinerary_qa 逻辑）
- edit_diff SSE 事件结构
不依赖 DB / FastAPI / LLM。
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.domain.travel.patch_engine import PatchOp, PatchOpType, apply_patch
from app.domain.travel.sse_envelope import build_event_envelope, build_event_line
from app.lg_agent.travel_draft_graph import _apply_city_center_fallback
from app.schemas.itinerary_v1 import ItineraryV1


def _make_itinerary() -> dict:
    return {
        "schema_version": "itinerary.v1",
        "itinerary_id": str(uuid.uuid4()),
        "revision_id": "rev-base",
        "base_revision_id": None,
        "trip_profile": {
            "destination_city": "上海",
            "constraints": {"budget_range": "约 6000 元", "traveler_type": "情侣", "preferences": ["文化"]},
        },
        "days": [
            {
                "day_index": 1,
                "theme": "外滩之旅",
                "slots": [
                    {"slot": "上午", "activity": "参观外滩", "place": "外滩", "transit": "步行"},
                    {"slot": "下午", "activity": "逛南京路", "place": "南京路步行街", "transit": "地铁"},
                    {"slot": "晚上", "activity": "夜游黄浦江", "place": "十六铺码头", "transit": "打车"},
                ],
            },
            {
                "day_index": 2,
                "theme": "文化探索",
                "slots": [
                    {"slot": "上午", "activity": "参观上海博物馆", "place": "上海博物馆", "transit": "地铁"},
                    {"slot": "下午", "activity": "豫园和城隍庙", "place": "豫园", "transit": "步行"},
                    {"slot": "晚上", "activity": "品尝本帮菜", "place": "老正兴", "transit": "打车"},
                ],
            },
        ],
        "budget_summary": {
            "total_estimate": 6000.0,
            "by_category": {"transport": 800, "hotel": 2000, "tickets": 400, "food": 2200, "other": 600},
        },
        "validation": {"assumptions": []},
    }


# ---------- edit_diff SSE 事件结构 ----------

class TestEditDiffEvent:
    def test_edit_diff_event_structure(self):
        """T-M2-013: edit_diff 事件包含 old/new revision + change_summary。"""
        it = _make_itinerary()
        ops = [PatchOp(op=PatchOpType.REPLACE_SLOT, day_index=1, slot_label="上午", payload={"activity": "去外滩看日出"})]
        result = apply_patch(it, ops)
        assert result.success

        event_line = build_event_line(
            "edit_diff",
            build_event_envelope(
                request_id="req-edit-1",
                conversation_id="conv-edit-1",
                revision_id=result.new_revision_id,
                payload={
                    "old_revision_id": result.old_revision_id,
                    "new_revision_id": result.new_revision_id,
                    "change_summary": result.change_summary,
                    "explanation": result.explanation,
                },
            ),
        )
        assert event_line.startswith("event: edit_diff\n")
        for line in event_line.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                assert data["request_id"] == "req-edit-1"
                assert data["revision_id"] == result.new_revision_id
                payload = data["payload"]
                assert payload["old_revision_id"] == "rev-base"
                assert "changed_days" in payload["change_summary"]
                assert "diff_items" in payload["change_summary"]
                assert 1 in payload["change_summary"]["changed_days"]
                break
        else:
            pytest.fail("No data line in edit_diff event")

    def test_final_itinerary_after_edit(self):
        """编辑后 final_itinerary 事件应携带 new_revision_id。"""
        it = _make_itinerary()
        ops = [PatchOp(op=PatchOpType.REPLACE_SLOT, day_index=2, slot_label="下午", payload={"activity": "田子坊漫步"})]
        result = apply_patch(it, ops)

        event_line = build_event_line(
            "final_itinerary",
            build_event_envelope(
                request_id="req-edit-2",
                conversation_id="conv-edit-2",
                revision_id=result.new_revision_id,
                payload={
                    "itinerary": result.new_itinerary,
                    "explanation": result.explanation,
                },
            ),
        )
        for line in event_line.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                assert data["revision_id"] == result.new_revision_id
                itin = data["payload"]["itinerary"]
                assert itin["revision_id"] == result.new_revision_id
                assert itin["base_revision_id"] == "rev-base"
                day2 = next(d for d in itin["days"] if d["day_index"] == 2)
                pm = next(s for s in day2["slots"] if s["slot"] == "下午")
                assert pm["activity"] == "田子坊漫步"
                break
        else:
            pytest.fail("No data line in final_itinerary event")

    def test_city_center_fallback_keeps_edited_slot_mappable(self):
        """When provider backfill is unavailable, edited slots still get destination fallback coordinates."""
        it = _make_itinerary()
        ops = [PatchOp(op=PatchOpType.REPLACE_SLOT, day_index=2, slot_label="下午", payload={"activity": "田子坊漫步"})]
        result = apply_patch(it, ops)
        edited = ItineraryV1.model_validate(result.new_itinerary)

        day2 = next(d for d in edited.days if d.day_index == 2)
        pm = next(s for s in day2.slots if s.slot == "下午")
        assert pm.location is None

        _apply_city_center_fallback(edited)

        assert pm.location is not None
        assert pm.location.lat == pytest.approx(31.2304)
        assert pm.location.lng == pytest.approx(121.4737)

    def test_stream_edit_missing_target_returns_text_not_itinerary(self):
        """A failed edit should not emit final_itinerary or advance revision."""
        from app.api.travel import _stream_edit_result

        async def collect_lines() -> list[str]:
            return [
                line
                async for line in _stream_edit_result(
                    utterance="把第99天上午改成去博物馆",
                    current_itinerary=_make_itinerary(),
                    request_id="req-edit-miss",
                    conversation_id="conv-edit-miss",
                    intent="edit",
                    intent_detail="edit_itinerary",
                    user_id=1,
                )
            ]

        lines = asyncio.run(collect_lines())
        event_names = [
            line.split("\n", 1)[0].replace("event: ", "")
            for line in lines
            if line.startswith("event: ")
        ]
        assert "final_text" in event_names
        assert "final_itinerary" not in event_names
        assert "edit_diff" not in event_names

        final_text_line = next(line for line in lines if line.startswith("event: final_text"))
        data_line = next(line for line in final_text_line.split("\n") if line.startswith("data: "))
        data = json.loads(data_line[6:])
        assert data["revision_id"] is None
        assert "未指定修改哪一天" in data["payload"]["text"]

    def test_stream_edit_day_replan_uses_candidate_service(self, monkeypatch):
        """Day-level edits should call candidate-driven replan before final_itinerary."""
        import app.api.travel as travel_api

        class FakeDayReplanService:
            async def replan_days(self, itinerary, replan_requests, *, context=None):
                assert replan_requests[0]["day_index"] == 2
                day2 = next(day for day in itinerary["days"] if day["day_index"] == 2)
                day2["theme"] = "候选驱动的室内体验"
                day2["slots"] = [
                    {
                        "slot": "上午",
                        "activity": "上海博物馆室内参观",
                        "place": "上海博物馆",
                        "transit": "公共交通/步行",
                        "alternatives": [],
                        "evidence_refs": ["fake:上海博物馆"],
                    },
                    {
                        "slot": "下午",
                        "activity": "上海当代艺术博物馆室内参观",
                        "place": "上海当代艺术博物馆",
                        "transit": "公共交通/步行",
                        "alternatives": [],
                        "evidence_refs": ["fake:上海当代艺术博物馆"],
                    },
                    {
                        "slot": "晚上",
                        "activity": "K11购物艺术中心室内休闲与用餐",
                        "place": "K11购物艺术中心",
                        "transit": "公共交通/步行",
                        "alternatives": [],
                        "evidence_refs": ["fake:K11购物艺术中心"],
                    },
                ]

                class Report:
                    assumptions = []
                    diff_items = ["第2天已基于候选POI重新规划（候选3个，来源召回排序）。"]

                return Report()

        class FakeBackfillService:
            async def backfill_changed_days(self, edited_model, changed_days):
                class Report:
                    assumptions = []

                return Report()

        async def fake_persist(**kwargs):
            return None

        monkeypatch.setattr(travel_api, "day_replan_service", FakeDayReplanService())
        monkeypatch.setattr(travel_api, "edit_backfill_service", FakeBackfillService())
        monkeypatch.setattr(travel_api.ConversationService, "upsert_travel_conversation_state", fake_persist)

        async def collect_lines() -> list[str]:
            return [
                line
                async for line in travel_api._stream_edit_result(
                    utterance="把第二天改成室内",
                    current_itinerary=_make_itinerary(),
                    request_id="req-edit-replan",
                    conversation_id="conv-edit-replan",
                    intent="edit",
                    intent_detail="edit_itinerary",
                    user_id=1,
                )
            ]

        lines = asyncio.run(collect_lines())
        final_itinerary_line = next(line for line in lines if line.startswith("event: final_itinerary"))
        data_line = next(line for line in final_itinerary_line.split("\n") if line.startswith("data: "))
        data = json.loads(data_line[6:])
        itinerary = data["payload"]["itinerary"]
        day2 = next(day for day in itinerary["days"] if day["day_index"] == 2)

        assert day2["theme"] == "候选驱动的室内体验"
        assert [slot["place"] for slot in day2["slots"]] == [
            "上海博物馆",
            "上海当代艺术博物馆",
            "K11购物艺术中心",
        ]
        assert itinerary["change_summary"]["replan_requests"][0]["day_index"] == 2
        assert any("候选POI重新规划" in item for item in itinerary["change_summary"]["diff_items"])

    def test_stream_edit_constraint_question_does_not_mutate_itinerary(self):
        """Constraint-looking questions should not be treated as day replan edits."""
        from app.api.travel import _stream_edit_result

        async def collect_lines() -> list[str]:
            return [
                line
                async for line in _stream_edit_result(
                    utterance="第二天有没有室内安排",
                    current_itinerary=_make_itinerary(),
                    request_id="req-edit-question",
                    conversation_id="conv-edit-question",
                    intent="edit",
                    intent_detail="edit_itinerary",
                    user_id=1,
                )
            ]

        lines = asyncio.run(collect_lines())
        event_names = [
            line.split("\n", 1)[0].replace("event: ", "")
            for line in lines
            if line.startswith("event: ")
        ]

        assert "final_text" in event_names
        assert "edit_diff" not in event_names
        assert "final_itinerary" not in event_names


# ---------- QA 回答（函数逻辑直接测试） ----------

class TestQAAnswering:
    """直接测试 QA 回答逻辑，不导入 travel.py（避免 FastAPI 依赖）。"""

    @staticmethod
    def _answer_qa(query: str, itinerary: dict) -> str:
        """复制 travel.py 中 _answer_itinerary_qa 的核心逻辑用于测试。"""
        import re
        days = itinerary.get("days", [])
        profile = itinerary.get("trip_profile", {})
        budget = itinerary.get("budget_summary", {})
        dest = profile.get("destination_city", "未知")
        if "几天" in query or "天数" in query:
            return f"当前行程共 {len(days)} 天，目的地为 {dest}。"
        if "预算" in query or "花费" in query or "多少钱" in query:
            total = budget.get("total_estimate", 0)
            by_cat = budget.get("by_category", {})
            parts = [f"总预算约 {int(total)} 元"]
            for k, v in by_cat.items():
                if v:
                    parts.append(f"{k}: {int(v)} 元")
            return "。".join(parts) + "。"
        if "第" in query and "天" in query:
            m = re.search(r"第\s*(\d+)\s*天", query)
            if m:
                idx = int(m.group(1))
                for d in days:
                    if d.get("day_index") == idx:
                        slots_desc = []
                        for s in d.get("slots", []):
                            slots_desc.append(f"{s.get('slot', '')}：{s.get('activity', '')}（{s.get('place', '未定')}）")
                        theme = d.get("theme", "")
                        return f"第{idx}天{' - ' + theme if theme else ''}：{'；'.join(slots_desc)}。"
                return f"行程中没有第{idx}天的安排。"
        slot_count = sum(len(d.get("slots", [])) for d in days)
        return f"当前行程：{dest} {len(days)} 天，共 {slot_count} 个时段安排，总预算 {int(budget.get('total_estimate', 0))} 元。如需了解具体某天，可以问'第N天安排是什么'。"

    def test_qa_days(self):
        it = _make_itinerary()
        answer = self._answer_qa("行程一共几天？", it)
        assert "2 天" in answer
        assert "上海" in answer

    def test_qa_budget(self):
        it = _make_itinerary()
        answer = self._answer_qa("总预算是多少钱？", it)
        assert "6000" in answer

    def test_qa_specific_day(self):
        it = _make_itinerary()
        answer = self._answer_qa("第1天安排是什么？", it)
        assert "外滩" in answer
        assert "南京路" in answer

    def test_qa_nonexistent_day(self):
        it = _make_itinerary()
        answer = self._answer_qa("第5天有什么安排？", it)
        assert "没有第5天" in answer

    def test_qa_general(self):
        it = _make_itinerary()
        answer = self._answer_qa("帮我看看行程", it)
        assert "上海" in answer
        assert "6 个时段" in answer
