"""
T-M2-011 对话意图路由 相关单元测试。
- QP 意图识别：reset / edit / qa / create
- QP 约束抽取与 recall_query
- 不依赖 DB，不启动 FastAPI。
"""
from __future__ import annotations

import json
import re

import pytest

from app.domain.travel.query_processor import TravelQueryProcessor


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
    for query in ("第2天安排是什么？", "第1天几点出发?", "day 2 有什么安排？"):
        out = processor.process(query)
        assert out["intent"] == "qa"
        assert out["intent_detail"] == "qa_local"


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
