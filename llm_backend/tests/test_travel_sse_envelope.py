import json
from typing import Optional, Tuple

from app.domain.travel.sse_envelope import (
    build_data_line,
    build_event_envelope,
    build_event_line,
)
from app.services.travel_clarification_service import TravelClarificationService


def _parse_sse_chunk(chunk: str) -> Tuple[Optional[str], dict]:
    lines = [line for line in chunk.splitlines() if line.strip()]
    event = None
    data_line = None
    for line in lines:
        if line.startswith("event: "):
            event = line.replace("event: ", "", 1)
        if line.startswith("data: "):
            data_line = line.replace("data: ", "", 1)
    assert data_line is not None
    return event, json.loads(data_line)


def test_build_event_envelope_contains_required_fields():
    data = build_event_envelope(
        request_id="req_001",
        conversation_id="conv_001",
        revision_id="rev_001",
        payload={"x": 1},
    )
    assert data["request_id"] == "req_001"
    assert data["conversation_id"] == "conv_001"
    assert data["revision_id"] == "rev_001"
    assert data["payload"] == {"x": 1}
    assert "timestamp" in data


def test_build_event_line_uses_sse_event_and_data_format():
    chunk = build_event_line(
        "final_text",
        build_event_envelope(
            request_id="req_001",
            conversation_id="conv_001",
            revision_id=None,
            payload={"text": "hello"},
        ),
    )
    event_1, data_1 = _parse_sse_chunk(chunk)
    assert event_1 == "final_text"
    assert data_1["payload"]["text"] == "hello"


def test_build_data_line_supports_text_fallback():
    chunk = build_data_line("fallback text")
    assert chunk.startswith("data: ")
    assert "\"fallback text\"" in chunk


def test_clarification_payload_contains_stage_and_missing_fields():
    service = TravelClarificationService()
    payload = service.build_clarification_payload(
        missing_hard=["destination"],
        missing_soft=["travelers"],
    )
    assert payload["stage"] == "clarify_constraints"
    assert payload["missing_required"] == ["destination"]
    assert payload["missing_optional"] == ["travelers"]
    assert "message" in payload and payload["message"]


def test_clarification_stream_backward_compatible_text_fallback():
    service = TravelClarificationService()

    async def _collect():
        chunks = []
        async for chunk in service.build_clarification_stream(
            thread_id="conv_001",
            missing_hard=["destination"],
            missing_soft=["travelers"],
        ):
            chunks.append(chunk)
        return chunks

    import asyncio

    chunks = asyncio.run(_collect())
    assert len(chunks) == 3

    event_1, data_1 = _parse_sse_chunk(chunks[0])
    assert event_1 is None
    assert data_1["event"] == "stage_start"
    assert data_1["stage"] == "clarify_constraints"
    assert data_1["conversation_id"] == "conv_001"

    event_2, data_2 = _parse_sse_chunk(chunks[1])
    assert event_2 is None
    assert data_2["event"] == "stage_progress"
    assert data_2["missing_required"] == ["destination"]


def test_clarification_does_not_trigger_for_per_person_budget():
    service = TravelClarificationService()

    decision = service.start_new(
        thread_id="conv_hk",
        query="我想去香港，3天，人均2000",
    )

    assert decision["need_clarification"] is False
    assert decision["missing_hard"] == []
    assert not service.has_pending("conv_hk")


def test_clarification_does_not_trigger_for_planning_prefix_destination():
    service = TravelClarificationService()

    decision = service.start_new(
        thread_id="conv_sz",
        query="帮我规划深圳3天，预算中等",
    )

    assert decision["need_clarification"] is False
    assert decision["missing_hard"] == []
    assert not service.has_pending("conv_sz")


def test_clarification_completes_when_pending_budget_gets_per_person_value():
    service = TravelClarificationService()

    first = service.start_new(thread_id="conv_budget", query="我想去香港，3天")
    assert first["need_clarification"] is True
    assert service.has_pending("conv_budget")

    decision = service.continue_pending(
        thread_id="conv_budget",
        query="人均2000",
    )

    assert decision["need_clarification"] is False
    assert decision["combined_query"] == "去香港，玩3天，预算2000元"
    assert not service.has_pending("conv_budget")


def test_clarification_snapshot_restores_in_fresh_service():
    first = TravelClarificationService()
    first.start_new(thread_id="conv_restore", query="我想去香港")

    snapshot = first.snapshot_pending("conv_restore")
    restored = TravelClarificationService()
    restored.restore_pending("conv_restore", snapshot)

    assert restored.has_pending("conv_restore")
    assert restored.snapshot_pending("conv_restore") == snapshot


def test_clarification_snapshot_is_a_defensive_copy():
    service = TravelClarificationService()
    service.start_new(thread_id="conv_copy", query="我想去香港")

    snapshot = service.snapshot_pending("conv_copy")
    assert snapshot is not None
    snapshot["values"]["destination"] = "澳门"

    fresh = service.snapshot_pending("conv_copy")
    assert fresh is not None
    assert fresh["values"]["destination"] == "香港"


def test_flexible_answer_applies_duration_and_budget_defaults_when_destination_known():
    service = TravelClarificationService()
    first = service.start_new(thread_id="conv_flexible", query="我想去香港")

    assert first["need_clarification"] is True
    assert service.has_pending("conv_flexible")

    decision = service.continue_pending(thread_id="conv_flexible", query="都可以")

    assert decision["need_clarification"] is False
    assert "玩3天" in decision["combined_query"]
    assert "预算6000元" in decision["combined_query"]
    assert decision["assumptions"] == [
        "duration_defaulted_from_flexible_answer",
        "budget_defaulted_from_flexible_answer",
    ]
    assert not service.has_pending("conv_flexible")


def test_flexible_answer_never_invents_missing_destination():
    service = TravelClarificationService()
    service.start_new(thread_id="conv_missing_destination", query="预算5000")

    decision = service.continue_pending(
        thread_id="conv_missing_destination",
        query="你安排就好",
    )

    assert decision["need_clarification"] is True
    assert decision["missing_hard"] == ["destination"]
    snapshot = service.snapshot_pending("conv_missing_destination")
    assert snapshot is not None
    assert snapshot["values"]["destination"] is None
    assert snapshot["values"]["duration"] == 3
    assert snapshot["values"]["budget"] == 5000
    assert snapshot["asked_fields"] == ["destination", "duration"]


def test_budget_only_clarification_treats_vague_confirmations_as_ambiguous():
    from app.api.travel import _needs_budget_clarification_hint

    for query in ("都可以", "好的", "随便", "都行"):
        assert _needs_budget_clarification_hint(query=query, missing_text="预算范围") is True


def test_travel_request_fingerprint_dedupes_active_request(monkeypatch):
    from app.api import travel

    monkeypatch.setattr(travel.settings, "TRAVEL_REQUEST_DEDUPE_TTL_SECONDS", 5.0)
    travel._active_request_fingerprints.clear()

    fingerprint = travel._request_fingerprint(
        user_id=1,
        conversation_id="conv_001",
        query="上海 3天 预算5000",
    )
    assert travel._try_acquire_request_fingerprint(fingerprint) is True
    assert travel._try_acquire_request_fingerprint(fingerprint) is False

    travel._release_request_fingerprint(fingerprint)
    assert travel._try_acquire_request_fingerprint(fingerprint) is True
    travel._active_request_fingerprints.clear()


def test_answer_itinerary_qa_supports_chinese_day_number():
    from app.api.travel import _answer_itinerary_qa

    itinerary = {
        "trip_profile": {"destination_city": "成都"},
        "days": [
            {
                "day_index": 2,
                "theme": "亲子乐园与城市文化",
                "slots": [
                    {"slot": "上午", "activity": "亲子乐园", "place": "亲子乐园"},
                    {"slot": "下午", "activity": "室内活动", "place": "四川科技馆"},
                ],
            }
        ],
        "budget_summary": {"total_estimate": 6000},
    }

    text = _answer_itinerary_qa("第二天安排是什么？", itinerary)

    assert "第2天" in text
    assert "亲子乐园" in text
    assert "四川科技馆" in text


def test_answer_itinerary_qa_uses_english_for_english_day_question():
    from app.api.travel import _answer_itinerary_qa

    itinerary = {
        "trip_profile": {"destination_city": "Phuket"},
        "days": [
            {
                "day_index": 2,
                "theme": "Beach and food",
                "slots": [
                    {"slot": "morning", "activity": "Relax on Kata Beach", "place": "Kata Beach"},
                    {"slot": "afternoon", "activity": "Thai cooking class", "place": "Cooking Academy"},
                ],
            }
        ],
        "budget_summary": {"total_estimate": 6000},
    }

    text = _answer_itinerary_qa("What is the plan for day 2?", itinerary)

    assert text.startswith("Day 2")
    assert "Kata Beach" in text
    assert "Cooking Academy" in text
    assert "当前行程" not in text


def test_answer_itinerary_qa_uses_english_for_english_budget_question():
    from app.api.travel import _answer_itinerary_qa

    itinerary = {
        "trip_profile": {"destination_city": "Phuket"},
        "days": [],
        "budget_summary": {
            "total_estimate": 6000,
            "by_category": {"food": 1200, "tickets": 800},
        },
    }

    text = _answer_itinerary_qa("What is the budget?", itinerary)

    assert "Total budget is about 6000 CNY" in text
    assert "food: 1200 CNY" in text


def test_classify_local_qa_fast_path_only_accepts_qa():
    from app.api.travel import _classify_local_qa_fast_path

    assert _classify_local_qa_fast_path("第 2 天安排是什么？")["intent"] == "qa"
    assert _classify_local_qa_fast_path("把第 2 天改成东方明珠") is None


def test_build_local_qa_fast_response_returns_sse_without_structured_qp(monkeypatch):
    import asyncio

    from app.api import travel

    itinerary = {
        "trip_profile": {"destination_city": "成都"},
        "days": [
            {
                "day_index": 2,
                "theme": "亲子乐园与城市文化",
                "slots": [{"slot": "上午", "activity": "亲子乐园", "place": "亲子乐园"}],
            }
        ],
        "budget_summary": {"total_estimate": 6000},
    }

    async def fake_get_state(conversation_id: str):
        assert conversation_id == "conv_qa"
        return {"current_itinerary": itinerary}

    async def fake_upsert(**kwargs):
        assert kwargs["conversation_id"] == "conv_qa"
        assert kwargs["last_user_query"] == "第 2 天安排是什么？"
        return kwargs

    async def fail_process_qp(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("local QA fast path should not call Structured QP")

    monkeypatch.setattr(travel.ConversationService, "get_travel_conversation_state", fake_get_state)
    monkeypatch.setattr(travel.ConversationService, "upsert_travel_conversation_state", fake_upsert)
    monkeypatch.setattr(travel, "_process_qp", fail_process_qp)

    async def collect():
        response = await travel._build_local_qa_fast_response(
            request_id="req_qa",
            conversation_id="conv_qa",
            query_text="第 2 天安排是什么？",
            user_id=1,
        )
        assert response is not None
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    event_1, data_1 = _parse_sse_chunk(chunks[0])
    event_2, data_2 = _parse_sse_chunk(chunks[1])

    assert event_1 == "intent_routed"
    assert data_1["payload"]["intent"] == "qa"
    assert event_2 == "final_text"
    assert data_2["payload"]["qa_source"] == "local_itinerary"
    assert "亲子乐园" in data_2["payload"]["text"]


def test_build_local_qa_fast_response_preserves_english_language(monkeypatch):
    import asyncio

    from app.api import travel

    itinerary = {
        "trip_profile": {"destination_city": "Phuket"},
        "days": [
            {
                "day_index": 2,
                "theme": "Beach day",
                "slots": [{"slot": "morning", "activity": "Relax on Kata Beach", "place": "Kata Beach"}],
            }
        ],
        "budget_summary": {"total_estimate": 6000},
    }

    async def fake_get_state(conversation_id: str):
        assert conversation_id == "conv_qa_en"
        return {"current_itinerary": itinerary}

    async def fake_upsert(**kwargs):
        assert kwargs["conversation_id"] == "conv_qa_en"
        assert kwargs["last_user_query"] == "What is the plan for day 2?"
        return kwargs

    monkeypatch.setattr(travel.ConversationService, "get_travel_conversation_state", fake_get_state)
    monkeypatch.setattr(travel.ConversationService, "upsert_travel_conversation_state", fake_upsert)

    async def collect():
        response = await travel._build_local_qa_fast_response(
            request_id="req_qa_en",
            conversation_id="conv_qa_en",
            query_text="What is the plan for day 2?",
            user_id=1,
        )
        assert response is not None
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    event_2, data_2 = _parse_sse_chunk(chunks[1])

    assert event_2 == "final_text"
    assert data_2["payload"]["response_language"] == "en"
    assert data_2["payload"]["text"].startswith("Day 2")
