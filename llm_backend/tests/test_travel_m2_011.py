"""
T-M2-011 对话意图路由 相关单元测试。
- QP 意图识别：reset / edit / qa / create
- QP 约束抽取与 recall_query
- 不依赖 DB，不启动 FastAPI。
"""
from __future__ import annotations

import asyncio
import json
import re

import pytest

from app.domain.travel.query_processor import TravelQueryProcessor
from app.domain.travel.structured_qp import StructuredQPConstraints, StructuredQPResult


class _FakeStructuredQPStrategy:
    def __init__(self, result: StructuredQPResult | Exception):
        self.result = result
        self.seen_context = None
        self.call_count = 0

    async def classify(self, query: str, *, context=None):
        self.call_count += 1
        self.seen_context = context
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


# ---------- 意图识别 ----------


def test_qp_intent_reset():
    processor = TravelQueryProcessor()
    for query in ("重置", "重新开始", "清空行程", "从头开始", "reset", "restart"):
        out = processor.process(query)
        assert out["intent"] == "reset"
        assert out["intent_detail"] == "reset_all"


def test_qp_intent_edit_with_full_constraints_becomes_create():
    """Edit keywords + full P0 constraints (dest+days+budget) → create, not edit."""
    processor = TravelQueryProcessor()
    out = processor.process("帮我改一下，去成都3天预算5000")
    assert out["intent"] == "create", (
        f"Expected 'create' for full-constraint query with edit keyword, got '{out['intent']}'"
    )


def test_qp_intent_edit():
    processor = TravelQueryProcessor()
    for query in ("修改第二天", "把第1天改成博物馆", "调整一下行程", "替换成别的"):
        out = processor.process(query)
        assert out["intent"] == "edit"
        assert out["intent_detail"] == "edit_day"


def test_qp_day_question_is_qa_not_edit():
    processor = TravelQueryProcessor()
    for query in (
        "第2天安排是什么？",
        "第1天几点出发?",
        "day 2 有什么安排？",
        "第三天下午去哪里",
        "第三天下午去哪",
        "第二天晚上有什么",
        "第2天安排啥",
    ):
        out = processor.process(query)
        assert out["intent"] == "qa"
        assert out["intent_detail"] == "qa_local"
        assert out["missing_required"] == []


def test_qp_readonly_mutation_question_is_qa_not_edit():
    processor = TravelQueryProcessor()
    for query in ("第二天改成室内了吗？", "第3天晚上有没有被调整？"):
        out = processor.process(query)
        assert out["intent"] == "qa"
        assert out["intent_detail"] == "qa_local"


def test_qp_day_reference_without_mutation_is_read_only_qa():
    processor = TravelQueryProcessor()
    for query in ("第三天下午", "第二天室内一点", "day 2 afternoon"):
        out = processor.process(query)
        assert out["intent"] == "qa"
        assert out["intent_detail"] == "qa_local"


def test_qp_explicit_mutation_still_routes_to_edit():
    processor = TravelQueryProcessor()
    for query in ("能不能把第二天改成室内？", "第二天别太赶", "删掉第3天晚上"):
        out = processor.process(query)
        assert out["intent"] == "edit"
        assert out["intent_detail"] == "edit_day"
        assert out["missing_required"] == []


@pytest.mark.parametrize(
    ("query", "intent", "day", "slot"),
    [
        ("第三天下午去哪里？", "qa", 3, "下午"),
        ("把第二天晚上改成美食活动", "edit", 2, "晚上"),
        ("What happens on day two?", "qa", 2, None),
        ("Change the third afternoon to an indoor activity", "edit", 3, "下午"),
        ("Replace the second evening with food", "edit", 2, "晚上"),
    ],
)
def test_qp_rule_extracts_target_day_and_slot(query, intent, day, slot):
    out = TravelQueryProcessor().process(query)

    assert out["intent"] == intent
    assert out["target_day"] == day
    assert out["target_slot"] == slot


@pytest.mark.parametrize(
    "query",
    [
        "先别改",
        "我只是问交通，不要换目的地",
        "先不要真的修改",
        "刚才两次修改都保留",
        "Do not change my current trip",
    ],
)
def test_qp_negated_or_preserving_mutation_language_is_read_only(query):
    out = TravelQueryProcessor().process(query)

    assert out["intent"] in {"qa", "chat"}


@pytest.mark.parametrize(
    ("query", "destination"),
    [
        ("不去澳门了，换成厦门", "厦门"),
        ("Change the destination to Kyoto", "Kyoto"),
        ("Let's go to Paris instead", "Paris"),
        ("Let's switch the trip to Oaxaca", "Oaxaca"),
        ("帮我规划深圳", "深圳"),
    ],
)
def test_qp_extracts_destination_from_general_replacement_and_planning_phrases(
    query,
    destination,
):
    out = TravelQueryProcessor().process(query)

    assert out["constraints"]["destination_city"] == destination


def test_qp_local_day_edit_does_not_extract_activity_as_destination():
    out = TravelQueryProcessor().process("把第二天下午改成室内活动")

    assert out["intent"] == "edit"
    assert out["constraints"]["destination_city"] is None


@pytest.mark.parametrize(
    "query",
    [
        "上海和苏州哪个更适合周末？",
        "Is Osaka better than Kyoto for food?",
        "How do I get from Paris to London?",
        "Why did you choose that place?",
        "How busy is day two?",
    ],
)
def test_qp_travel_comparison_and_itinerary_questions_are_read_only_qa(query):
    out = TravelQueryProcessor().process(query)

    assert out["intent"] == "qa"


def test_qp_english_clear_the_itinerary_is_reset():
    out = TravelQueryProcessor().process("Clear the itinerary")

    assert out["intent"] == "reset"


@pytest.mark.parametrize(
    ("query", "intent", "day"),
    [
        ("先看看当前预算", "qa", None),
        ("day two?", "qa", 2),
        ("Plan Berlin for four days with 9000 yuan", "create", None),
    ],
)
def test_qp_understands_readonly_requests_word_days_and_english_plan(
    query,
    intent,
    day,
):
    out = TravelQueryProcessor().process(query)

    assert out["intent"] == intent
    assert out["target_day"] == day
    if intent == "create":
        assert out["constraints"]["destination_city"] == "Berlin"
        assert out["constraints"]["days"] == 4
        assert out["constraints"]["budget"] == 9000.0


def test_qp_intent_qa_evidence():
    processor = TravelQueryProcessor()
    for query in ("为什么推荐这个", "证据在哪", "来源链接"):
        out = processor.process(query)
        assert out["intent"] == "qa"
        assert out["intent_detail"] in ("qa_evidence", "qa_local")


def test_qp_intent_create():
    processor = TravelQueryProcessor()
    out = processor.process("travel to shanghai for 4 days, budget 6000, couple, prefer culture and food")
    assert out["intent"] == "create"
    assert out["intent_detail"] == "first_create"


def test_qp_create_with_duration_and_qualitative_budget_is_not_edit():
    processor = TravelQueryProcessor()
    out = processor.process("帮我规划 3 天成都亲子游，预算中等，节奏轻松")
    assert out["intent"] == "create"
    assert out["intent_detail"] == "first_create"
    assert out["constraints"]["destination_city"] == "成都"
    assert out["constraints"]["days"] == 3
    assert out["constraints"]["budget"] == 6000.0
    assert out["missing_required"] == []


def test_qp_create_with_planning_prefix_extracts_destination_before_duration():
    processor = TravelQueryProcessor()
    for query, city in (
        ("帮我规划深圳3天，预算中等", "深圳"),
        ("安排澳门5天，预算人均5000", "澳门"),
        ("做一个成都4天行程，预算中等", "成都"),
    ):
        out = processor.process(query)
        assert out["intent"] == "create"
        assert out["intent_detail"] == "first_create"
        assert out["constraints"]["destination_city"] == city
        assert out["constraints"]["days"] is not None
        assert out["constraints"]["budget"] is not None
        assert out["missing_required"] == []


def test_qp_extracts_per_person_budget_for_create():
    processor = TravelQueryProcessor()
    for query in (
        "我想去香港，3天，人均2000",
        "香港3天，每人2000",
        "香港 3 天 2000/人",
        "香港3天，当地花销2000",
        "香港3天，不含住宿2000",
    ):
        out = processor.process(query)
        assert out["intent"] == "create"
        assert out["constraints"]["destination_city"] == "香港"
        assert out["constraints"]["days"] == 3
        assert out["constraints"]["budget"] == 2000.0
        assert out["missing_required"] == []


def test_qp_structured_strategy_can_drive_contextual_edit():
    strategy = _FakeStructuredQPStrategy(
        StructuredQPResult(
            intent="edit",
            intent_detail="edit_day",
            confidence=0.92,
            target_day=2,
            target_slot="afternoon",
            edit_constraints=["室内", "轻松"],
            constraints=StructuredQPConstraints(
                budget=5000,
                pace="relaxed",
                preferences=["亲子"],
            ),
            rewrite_query="把第 2 天节奏调轻松，预算保持 5000",
            reason="用户要求调整已有行程",
        )
    )
    processor = TravelQueryProcessor(
        structured_strategy=strategy,
        enable_structured_qp=True,
    )
    out = asyncio.run(
        processor.process_async(
            "预算还是5000，第二天别太赶",
            context={"has_itinerary": True, "trip_profile": {"destination_city": "成都"}},
        )
    )
    assert out["intent"] == "edit"
    assert out["intent_detail"] == "edit_day"
    assert out["qp_source"] == "llm"
    assert out["confidence"] == 0.92
    assert out["constraints"]["budget"] == 5000.0
    assert out["constraints"]["pace"] == "relaxed"
    assert out["rewrite_applied"] is True
    assert "节奏:relaxed" in out["recall_query"]
    assert strategy.seen_context.has_itinerary is True
    assert out["structured_qp_mode"] == "selective"
    assert out["route_reason"] == "selective:contextual_edit"
    assert out["safety_level"] == "safe"
    assert out["target_day"] == 2
    assert out["target_slot"] == "下午"
    assert out["edit_constraints"] == ["indoor", "relaxed"]


def test_qp_structured_strategy_low_confidence_falls_back_to_rule():
    strategy = _FakeStructuredQPStrategy(
        StructuredQPResult(
            intent="create",
            intent_detail="first_create",
            confidence=0.2,
            constraints=StructuredQPConstraints(destination_city="成都", days=3, budget=5000),
        )
    )
    processor = TravelQueryProcessor(
        structured_strategy=strategy,
        enable_structured_qp=True,
        confidence_threshold=0.65,
    )
    out = asyncio.run(processor.process_async("调整一下行程"))
    assert out["intent"] == "edit"
    assert out["qp_source"] == "rule"
    assert out["route_reason"] == "rule_fast_path"


def test_qp_structured_strategy_exception_falls_back_to_rule():
    processor = TravelQueryProcessor(
        structured_strategy=_FakeStructuredQPStrategy(RuntimeError("boom")),
        enable_structured_qp=True,
    )
    out = asyncio.run(processor.process_async("第2天安排是什么？"))
    assert out["intent"] == "qa"
    assert out["intent_detail"] == "qa_local"
    assert out["qp_source"] == "rule"
    assert out["route_reason"] == "rule_fast_path"


def test_qp_shadow_mode_keeps_rule_result_and_records_model_observation():
    strategy = _FakeStructuredQPStrategy(
        StructuredQPResult(
            intent="edit",
            intent_detail="edit_day",
            confidence=0.91,
            constraints=StructuredQPConstraints(budget=6000),
        )
    )
    processor = TravelQueryProcessor(
        structured_strategy=strategy,
        structured_qp_mode="shadow",
    )
    out = asyncio.run(
        processor.process_async(
            "住宿预算降一点，景点不要变",
            context={"has_itinerary": True},
        )
    )
    assert out["intent"] == "edit"
    assert out["qp_source"] == "rule"
    assert out["structured_qp_mode"] == "shadow"
    assert out["route_reason"] == "shadow:contextual_edit"
    assert out["shadow_intent"] == "edit"
    assert out["shadow_confidence"] == 0.91
    assert strategy.call_count == 1


def test_qp_selective_mode_blocks_model_create_over_existing_itinerary():
    strategy = _FakeStructuredQPStrategy(
        StructuredQPResult(
            intent="create",
            intent_detail="first_create",
            confidence=0.95,
            constraints=StructuredQPConstraints(destination_city="东京", days=3, budget=8000),
        )
    )
    processor = TravelQueryProcessor(
        structured_strategy=strategy,
        structured_qp_mode="selective",
    )
    out = asyncio.run(
        processor.process_async(
            "住宿预算降一点，景点不要变",
            context={"has_itinerary": True},
        )
    )
    assert out["intent"] == "edit"
    assert out["qp_source"] == "fallback"
    assert out["safety_level"] == "blocked"
    assert out["fallback_reason"] == "create_over_existing_itinerary"


def test_qp_selective_mode_blocks_model_edit_without_explicit_mutation():
    strategy = _FakeStructuredQPStrategy(
        StructuredQPResult(
            intent="edit",
            intent_detail="edit_day",
            confidence=0.95,
            constraints=StructuredQPConstraints(),
        )
    )
    processor = TravelQueryProcessor(
        structured_strategy=strategy,
        structured_qp_mode="selective",
    )
    out = asyncio.run(
        processor.process_async(
            "酒店位置怎么样",
            context={"has_itinerary": True},
        )
    )
    assert out["intent"] == "chat"
    assert out["qp_source"] == "fallback"
    assert out["safety_level"] == "blocked"
    assert out["fallback_reason"] == "edit_without_explicit_mutation"


def test_qp_selective_mode_uses_model_for_missing_destination():
    strategy = _FakeStructuredQPStrategy(
        StructuredQPResult(
            intent="create",
            intent_detail="first_create",
            confidence=0.93,
            constraints=StructuredQPConstraints(destination_city="Paris", days=3, budget=5000),
        )
    )
    processor = TravelQueryProcessor(
        structured_strategy=strategy,
        structured_qp_mode="selective",
    )
    out = asyncio.run(processor.process_async("Paris 3 days budget 5000 food"))
    assert out["intent"] == "create"
    assert out["qp_source"] == "llm"
    assert out["constraints"]["destination_city"] == "Paris"
    assert out["route_reason"] == "selective:missing_destination"


def test_qp_rule_fast_path_does_not_call_model_for_clear_local_edit():
    strategy = _FakeStructuredQPStrategy(
        StructuredQPResult(
            intent="chat",
            confidence=0.99,
        )
    )
    processor = TravelQueryProcessor(
        structured_strategy=strategy,
        structured_qp_mode="selective",
    )
    out = asyncio.run(
        processor.process_async(
            "把第2天下午改成室内博物馆",
            context={"has_itinerary": True},
        )
    )
    assert out["intent"] == "edit"
    assert out["qp_source"] == "rule"
    assert out["route_reason"] == "rule_fast_path"
    assert strategy.call_count == 0


def test_structured_qp_constraints_normalize_llm_surface_values():
    constraints = StructuredQPConstraints.model_validate({
        "budget": "中等",
        "pace": "slow",
    })
    assert constraints.budget == 6000.0
    assert constraints.pace == "relaxed"


def test_structured_qp_constraints_drop_non_numeric_budget_direction():
    constraints = StructuredQPConstraints.model_validate({"budget": "lower"})

    assert constraints.budget is None


def test_structured_qp_edit_fields_normalize_to_bounded_values():
    result = StructuredQPResult.model_validate({
        "intent": "edit",
        "intent_detail": "edit_day",
        "confidence": 0.91,
        "target_day": 2,
        "target_slot": "night",
        "edit_constraints": ["室内", "museum", "慢节奏", "未知标签"],
    })

    assert result.target_slot == "晚上"
    assert result.edit_constraints == ["indoor", "relaxed"]


# ---------- 约束抽取与 recall_query ----------


def test_qp_constraints_and_recall_query():
    processor = TravelQueryProcessor()
    query = "上海 4 天，预算 6000，情侣，偏好文化+美食"
    out = processor.process(query)
    assert out["constraints"]["destination_city"] == "上海"
    assert out["constraints"]["days"] == 4
    assert out["constraints"]["budget"] == 6000.0
    assert "情侣" in (out["constraints"]["traveler_type"] or "")
    assert "文化" in out["constraints"]["preferences"] or []
    assert "normalized_query" in out
    assert "recall_query" in out
    assert "上海" in out["recall_query"]
    assert "目的地:" in out["recall_query"]
    assert "天数:4" in out["recall_query"]
    assert "预算:6000" in out["recall_query"]


def test_qp_destination_prefers_city_before_duration_over_budget_token():
    processor = TravelQueryProcessor()
    for query, city in (
        ("上海 4天 预算6000 情侣 文化 美食", "上海"),
        ("北京 3天 预算5000 亲子", "北京"),
        ("成都 5天 预算8000 美食", "成都"),
    ):
        out = processor.process(query)
        assert out["constraints"]["destination_city"] == city


def test_qp_missing_required():
    processor = TravelQueryProcessor()
    out = processor.process("想去海边玩几天")
    assert "destination" in out["missing_required"] or "duration" in out["missing_required"] or "budget" in out["missing_required"]


# ---------- SSE 事件格式（仅校验构造的 payload 结构，不依赖 API） ----------


def test_intent_routed_event_structure():
    """校验 intent_routed 事件 payload 结构（与 travel.py 中 build_event_envelope 一致）。"""
    from app.domain.travel.sse_envelope import build_event_envelope, build_event_line

    event_line = build_event_line(
        "intent_routed",
        build_event_envelope(
            request_id="req-1",
            conversation_id="conv-1",
            revision_id=None,
            payload={"intent": "reset", "intent_detail": "reset_all"},
        ),
    )
    assert event_line.startswith("event: intent_routed\n")
    assert "data: " in event_line
    # 解析 data 行
    for line in event_line.split("\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])
            assert data["request_id"] == "req-1"
            assert data["conversation_id"] == "conv-1"
            assert data["payload"]["intent"] == "reset"
            assert data["payload"]["intent_detail"] == "reset_all"
            assert "timestamp" in data
            break
    else:
        pytest.fail("No data line in intent_routed event")


def test_reset_done_event_structure():
    """校验 reset_done 事件 payload 含 text。"""
    from app.domain.travel.sse_envelope import build_event_envelope, build_event_line

    event_line = build_event_line(
        "reset_done",
        build_event_envelope(
            request_id="req-1",
            conversation_id="conv-1",
            revision_id=None,
            payload={"text": "已为当前会话重置行程状态，你可以重新输入新的出行需求。"},
        ),
    )
    assert "event: reset_done" in event_line
    for line in event_line.split("\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])
            assert "已为当前会话重置" in data["payload"]["text"]
            break
    else:
        pytest.fail("No data line in reset_done event")
