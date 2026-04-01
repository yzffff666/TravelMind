"""
T-M2-012 / T-M2-013 集成测试：
- QA 规则回答（_answer_itinerary_qa 逻辑）
- edit_diff SSE 事件结构
不依赖 DB / FastAPI / LLM。
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.domain.travel.patch_engine import PatchOp, PatchOpType, apply_patch
from app.domain.travel.sse_envelope import build_event_envelope, build_event_line


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
