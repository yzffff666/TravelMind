"""
T-M2-012 Patch 编辑引擎单元测试。
覆盖：parse_edit_ops + apply_patch，不依赖 DB / FastAPI / LLM。
"""
from __future__ import annotations

import copy
import uuid

import pytest

from app.domain.travel.patch_engine import (
    PatchOp,
    PatchOpType,
    PatchResult,
    apply_patch,
    parse_edit_ops,
)


def _make_itinerary(days: int = 3, budget: float = 6000.0) -> dict:
    return {
        "schema_version": "itinerary.v1",
        "itinerary_id": str(uuid.uuid4()),
        "revision_id": "rev-old-001",
        "base_revision_id": None,
        "trip_profile": {
            "destination_city": "上海",
            "constraints": {
                "budget_range": f"约 {int(budget)} 元",
                "traveler_type": "情侣",
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
            for i in range(1, days + 1)
        ],
        "budget_summary": {
            "total_estimate": budget,
            "by_category": {"transport": 1000, "hotel": 2000, "tickets": 500, "food": 2000, "other": 500},
        },
        "validation": {"assumptions": []},
    }


# ---------- parse_edit_ops ----------

class TestParseEditOps:
    def test_replace_slot_with_day_and_slot(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第2天下午换成去博物馆", it)
        assert len(ops) >= 1
        op = ops[0]
        assert op.op == PatchOpType.REPLACE_SLOT
        assert op.day_index == 2
        assert op.slot_label == "下午"
        assert "博物馆" in op.payload.get("activity", "")

    def test_delete_slot(self):
        it = _make_itinerary()
        ops = parse_edit_ops("删掉第1天晚上", it)
        assert len(ops) >= 1
        assert ops[0].op == PatchOpType.DELETE_SLOT
        assert ops[0].day_index == 1
        assert ops[0].slot_label == "晚上"

    def test_insert_slot(self):
        it = _make_itinerary()
        ops = parse_edit_ops("第3天增加一个夜市活动", it)
        assert len(ops) >= 1
        assert ops[0].op == PatchOpType.INSERT_SLOT
        assert ops[0].day_index == 3

    def test_update_budget(self):
        it = _make_itinerary()
        ops = parse_edit_ops("预算改成8000", it)
        assert len(ops) >= 1
        assert ops[0].op == PatchOpType.UPDATE_CONSTRAINT
        assert ops[0].payload.get("budget") == 8000.0

    def test_fallback_to_replace(self):
        it = _make_itinerary()
        ops = parse_edit_ops("第1天上午想去外滩", it)
        assert len(ops) >= 1
        assert ops[0].day_index == 1

    def test_delete_whole_day(self):
        it = _make_itinerary()
        ops = parse_edit_ops("删掉第2天", it)
        assert len(ops) >= 1
        assert ops[0].op == PatchOpType.DELETE_SLOT
        assert ops[0].day_index == 2
        assert ops[0].slot_label is None


# ---------- apply_patch ----------

class TestApplyPatch:
    def test_replace_slot_success(self):
        it = _make_itinerary()
        ops = [PatchOp(op=PatchOpType.REPLACE_SLOT, day_index=1, slot_label="上午", payload={"activity": "去外滩"})]
        result = apply_patch(it, ops)
        assert result.success
        assert result.new_revision_id != "rev-old-001"
        assert result.old_revision_id == "rev-old-001"
        day1 = next(d for d in result.new_itinerary["days"] if d["day_index"] == 1)
        am_slot = next(s for s in day1["slots"] if s["slot"] == "上午")
        assert am_slot["activity"] == "去外滩"
        assert 1 in result.change_summary["changed_days"]
        assert result.new_itinerary["base_revision_id"] == "rev-old-001"

    def test_delete_slot_success(self):
        it = _make_itinerary()
        ops = [PatchOp(op=PatchOpType.DELETE_SLOT, day_index=2, slot_label="晚上")]
        result = apply_patch(it, ops)
        assert result.success
        day2 = next(d for d in result.new_itinerary["days"] if d["day_index"] == 2)
        slot_labels = [s["slot"] for s in day2["slots"]]
        assert "晚上" not in slot_labels
        assert 2 in result.change_summary["changed_days"]

    def test_insert_slot_success(self):
        it = _make_itinerary()
        ops = [PatchOp(op=PatchOpType.INSERT_SLOT, day_index=3, slot_label="晚上", payload={"activity": "逛夜市"})]
        result = apply_patch(it, ops)
        assert result.success
        day3 = next(d for d in result.new_itinerary["days"] if d["day_index"] == 3)
        assert len(day3["slots"]) == 4
        assert 3 in result.change_summary["changed_days"]

    def test_update_budget(self):
        it = _make_itinerary(budget=6000)
        ops = [PatchOp(op=PatchOpType.UPDATE_CONSTRAINT, payload={"budget": 8000.0})]
        result = apply_patch(it, ops)
        assert result.success
        assert result.new_itinerary["budget_summary"]["total_estimate"] == 8000.0
        assert any("8000" in d for d in result.change_summary["diff_items"])

    def test_empty_ops_returns_failure(self):
        it = _make_itinerary()
        result = apply_patch(it, [])
        assert not result.success
        assert result.error

    def test_original_not_mutated(self):
        it = _make_itinerary()
        original_rev = it["revision_id"]
        ops = [PatchOp(op=PatchOpType.REPLACE_SLOT, day_index=1, slot_label="上午", payload={"activity": "新活动"})]
        apply_patch(it, ops)
        assert it["revision_id"] == original_rev

    def test_change_summary_structure(self):
        it = _make_itinerary()
        ops = [PatchOp(op=PatchOpType.REPLACE_SLOT, day_index=1, slot_label="下午", payload={"activity": "游览豫园"})]
        result = apply_patch(it, ops)
        cs = result.new_itinerary.get("change_summary")
        assert cs is not None
        assert isinstance(cs["changed_days"], list)
        assert isinstance(cs["diff_items"], list)
        assert 1 in cs["changed_days"]

    def test_delete_all_slots_keeps_default(self):
        it = _make_itinerary()
        ops = [PatchOp(op=PatchOpType.DELETE_SLOT, day_index=1, slot_label=None)]
        result = apply_patch(it, ops)
        assert result.success
        day1 = next(d for d in result.new_itinerary["days"] if d["day_index"] == 1)
        assert len(day1["slots"]) >= 1
        assert day1["slots"][0]["activity"] == "自由活动"


# ---------- end-to-end: parse → apply ----------

class TestParseAndApply:
    def test_e2e_replace(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第2天下午换成逛南京路", it)
        result = apply_patch(it, ops)
        assert result.success
        assert 2 in result.change_summary["changed_days"]
        day2 = next(d for d in result.new_itinerary["days"] if d["day_index"] == 2)
        pm = next(s for s in day2["slots"] if s["slot"] == "下午")
        assert "南京路" in pm["activity"]

    def test_e2e_budget_change(self):
        it = _make_itinerary()
        ops = parse_edit_ops("预算改成10000", it)
        result = apply_patch(it, ops)
        assert result.success
        assert result.new_itinerary["budget_summary"]["total_estimate"] == 10000.0

    def test_e2e_delete_and_verify(self):
        it = _make_itinerary()
        ops = parse_edit_ops("删掉第3天晚上", it)
        result = apply_patch(it, ops)
        assert result.success
        day3 = next(d for d in result.new_itinerary["days"] if d["day_index"] == 3)
        labels = [s["slot"] for s in day3["slots"]]
        assert "晚上" not in labels
