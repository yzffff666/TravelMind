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
    has_mutation_intent,
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
    def test_mutation_intent_gate(self):
        assert has_mutation_intent("把第二天改成室内")
        assert has_mutation_intent("删掉第3天晚上")
        assert has_mutation_intent("第二天别太赶")
        assert has_mutation_intent("把第二天改轻松一点")
        assert has_mutation_intent("把第三天安排轻松一点")
        assert not has_mutation_intent("第三天下午去哪里")
        assert not has_mutation_intent("第2天安排是什么")

    def test_named_poi_replacement_becomes_verified_replan_request(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第2天下午换成逛南京路", it)
        assert len(ops) == 1
        op = ops[0]
        assert op.op == PatchOpType.REPLAN_DAY
        assert op.day_index == 2
        assert op.payload["target_slot"] == "下午"
        assert op.payload["explicit_place"] == "南京路"
        assert op.payload["execution_source"] == "rule_explicit_poi"

    def test_named_museum_is_not_reduced_to_generic_indoor_constraint(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第二天下午换成上海博物馆", it)

        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].payload["explicit_place"] == "上海博物馆"
        assert "indoor" in ops[0].payload["constraints"]

    def test_generic_indoor_museum_stays_constraint_replan(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第二天下午改成室内博物馆", it)

        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].payload.get("explicit_place") is None
        assert ops[0].payload["constraints"] == ["indoor"]

    def test_english_named_poi_replacement_is_supported(self):
        it = _make_itinerary()
        ops = parse_edit_ops("Change day 2 afternoon to Shanghai Museum", it)

        assert has_mutation_intent("Change day 2 afternoon to Shanghai Museum")
        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].day_index == 2
        assert ops[0].payload["target_slot"] == "下午"
        assert ops[0].payload["explicit_place"] == "Shanghai Museum"

    def test_english_day_question_is_not_an_edit(self):
        it = _make_itinerary()
        assert not has_mutation_intent("What is day 2 afternoon?")
        assert parse_edit_ops("What is day 2 afternoon?", it) == []

    def test_named_poi_without_slot_stays_deferred_instead_of_replacing_first_slot(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第二天换成东方明珠", it)

        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].day_index == 2
        assert ops[0].payload["target_slot"] is None
        assert ops[0].payload["explicit_place"] == "东方明珠"

    def test_english_generic_indoor_replan_does_not_become_raw_slot_text(self):
        it = _make_itinerary()
        ops = parse_edit_ops("Change day 2 to an indoor activity", it)

        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].payload.get("explicit_place") is None
        assert ops[0].payload["constraints"] == ["indoor"]

    @pytest.mark.parametrize(
        "utterance",
        ["把第九天下午换成上海博物馆", "Change day 9 afternoon to Shanghai Museum"],
    )
    def test_out_of_range_named_poi_edit_does_not_fallback_to_raw_replace(self, utterance):
        it = _make_itinerary()
        assert parse_edit_ops(utterance, it) == []

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

    def test_day_level_indoor_edit_becomes_replan_day(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第二天改成室内", it)
        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].day_index == 2
        assert "indoor" in ops[0].payload["constraints"]

    def test_slot_level_constraint_edit_becomes_targeted_replan_day(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第二天下午改成室内", it)

        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].day_index == 2
        assert ops[0].payload["target_slot"] == "下午"

    def test_day_level_relaxed_edit_becomes_replan_day_without_replace_hint(self):
        it = _make_itinerary()
        ops = parse_edit_ops("第二天别太赶", it)
        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].day_index == 2

    def test_day_level_relaxed_edit_with_plain_gai_becomes_replan_day(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第二天改轻松一点", it)
        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].day_index == 2
        assert "relaxed" in ops[0].payload["constraints"]

    def test_day_level_arrange_relaxed_becomes_replan_day(self):
        it = _make_itinerary()
        ops = parse_edit_ops("把第三天安排轻松一点", it)
        assert len(ops) == 1
        assert ops[0].op == PatchOpType.REPLAN_DAY
        assert ops[0].day_index == 3
        assert "relaxed" in ops[0].payload["constraints"]

    def test_day_level_constraint_question_does_not_become_replan_day(self):
        it = _make_itinerary()
        assert not has_mutation_intent("第二天有没有室内安排")
        assert parse_edit_ops("第二天有没有室内安排", it) == []
        assert parse_edit_ops("第三天下午去哪里", it) == []


# ---------- apply_patch ----------

class TestApplyPatch:
    def test_replace_slot_success(self):
        it = _make_itinerary()
        day1_original = next(d for d in it["days"] if d["day_index"] == 1)
        am_original = next(s for s in day1_original["slots"] if s["slot"] == "上午")
        am_original["location"] = {"lat": 31.2304, "lng": 121.4737}
        am_original["image_url"] = "https://example.com/old.jpg"
        am_original["evidence_refs"] = ["ev-old"]
        am_original["cost_breakdown"] = {"transport": 10}
        am_original["risk"] = {"level": "low", "text": "old"}
        ops = [PatchOp(op=PatchOpType.REPLACE_SLOT, day_index=1, slot_label="上午", payload={"activity": "去外滩"})]
        result = apply_patch(it, ops)
        assert result.success
        assert result.new_revision_id != "rev-old-001"
        assert result.old_revision_id == "rev-old-001"
        day1 = next(d for d in result.new_itinerary["days"] if d["day_index"] == 1)
        am_slot = next(s for s in day1["slots"] if s["slot"] == "上午")
        assert am_slot["activity"] == "去外滩"
        assert am_slot["place"] == "外滩"
        assert "location" not in am_slot
        assert "image_url" not in am_slot
        assert "transit" not in am_slot
        assert "cost_breakdown" not in am_slot
        assert "risk" not in am_slot
        assert am_slot["alternatives"] == []
        assert am_slot["evidence_refs"] == []
        assert result.new_itinerary["validation"]["coverage_score"] == 0.0
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

    def test_missing_target_day_returns_failure_without_revision(self):
        it = _make_itinerary()
        ops = [
            PatchOp(
                op=PatchOpType.REPLACE_SLOT,
                day_index=99,
                slot_label="上午",
                payload={"activity": "去博物馆"},
            )
        ]
        result = apply_patch(it, ops)
        assert not result.success
        assert result.new_itinerary is None
        assert result.new_revision_id is None
        assert "未找到第99天" in result.error

    def test_missing_target_slot_returns_failure_without_revision(self):
        it = _make_itinerary()
        ops = [
            PatchOp(
                op=PatchOpType.DELETE_SLOT,
                day_index=1,
                slot_label="凌晨",
            )
        ]
        result = apply_patch(it, ops)
        assert not result.success
        assert result.new_itinerary is None
        assert "未找到第1天的凌晨时段" in result.error

    def test_targeted_replan_records_request_without_template_mutation(self):
        it = _make_itinerary()
        original_day2 = copy.deepcopy(it["days"][1])
        result = apply_patch(
            it,
            [
                PatchOp(
                    op=PatchOpType.REPLAN_DAY,
                    day_index=2,
                    payload={"constraints": ["indoor"], "target_slot": "下午"},
                )
            ],
        )

        assert result.success
        assert result.new_itinerary["days"][1] == original_day2
        assert result.change_summary["replan_requests"] == [
            {
                "day_index": 2,
                "constraints": ["indoor"],
                "explicit_place": None,
                "raw_request": None,
                "anchor_locations": [],
                "target_slot": "下午",
                "execution_source": "rule",
            }
        ]

    def test_delete_slot_matches_normalized_label(self):
        it = _make_itinerary()
        ops = [PatchOp(op=PatchOpType.DELETE_SLOT, day_index=2, slot_label="morning")]
        result = apply_patch(it, ops)
        assert result.success
        day2 = next(d for d in result.new_itinerary["days"] if d["day_index"] == 2)
        slot_labels = [s["slot"] for s in day2["slots"]]
        assert "上午" not in slot_labels
        assert result.change_summary["failed_ops"] == 0

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

    def test_replan_day_replaces_whole_day_with_constraint_plan(self):
        it = _make_itinerary()
        it["trip_profile"]["destination_city"] = "香港"
        target_day = next(d for d in it["days"] if d["day_index"] == 2)
        target_day["slots"][0]["location"] = {"lat": 22.3027, "lng": 114.1772}
        original_day1 = copy.deepcopy(next(d for d in it["days"] if d["day_index"] == 1))
        original_day2 = copy.deepcopy(target_day)
        original_day3 = copy.deepcopy(next(d for d in it["days"] if d["day_index"] == 3))

        ops = parse_edit_ops("把第二天改成室内", it)
        result = apply_patch(it, ops)

        assert result.success
        assert 2 in result.change_summary["changed_days"]
        assert "重新规划" in result.change_summary["diff_items"][0]
        assert result.change_summary["replan_requests"][0]["day_index"] == 2
        assert "indoor" in result.change_summary["replan_requests"][0]["constraints"]
        assert result.change_summary["replan_requests"][0]["anchor_locations"] == [
            {"lat": 22.3027, "lng": 114.1772}
        ]

        assert next(d for d in result.new_itinerary["days"] if d["day_index"] == 1) == original_day1
        assert next(d for d in result.new_itinerary["days"] if d["day_index"] == 3) == original_day3

        day2 = next(d for d in result.new_itinerary["days"] if d["day_index"] == 2)
        assert day2 == original_day2


# ---------- end-to-end: parse → apply ----------

class TestParseAndApply:
    def test_e2e_named_poi_replacement_defers_mutation_until_provider_validation(self):
        it = _make_itinerary()
        original_day2 = copy.deepcopy(it["days"][1])
        ops = parse_edit_ops("把第2天下午换成逛南京路", it)
        result = apply_patch(it, ops)
        assert result.success
        assert 2 in result.change_summary["changed_days"]
        assert result.new_itinerary["days"][1] == original_day2
        request = result.change_summary["replan_requests"][0]
        assert request["explicit_place"] == "南京路"
        assert request["target_slot"] == "下午"
        assert "验证指定地点" in result.change_summary["diff_items"][0]

    def test_e2e_constraint_replan_with_chinese_day_number_defers_mutation(self):
        it = _make_itinerary()
        original_day2 = copy.deepcopy(it["days"][1])
        ops = parse_edit_ops("把第二天下午改成更轻松的室内活动", it)
        result = apply_patch(it, ops)

        assert result.success
        assert 2 in result.change_summary["changed_days"]
        assert result.new_itinerary["days"][1] == original_day2
        request = result.change_summary["replan_requests"][0]
        assert request["day_index"] == 2
        assert request["target_slot"] == "下午"
        assert request["constraints"] == ["indoor", "relaxed"]

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
