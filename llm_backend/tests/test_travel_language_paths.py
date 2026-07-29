from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.services.travel_clarification_service import TravelClarificationService


async def _chunks(stream) -> list[str]:
    return [chunk async for chunk in stream]


def _event_payload(chunks: list[str], event_name: str) -> dict:
    for chunk in chunks:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        if text.startswith(f"event: {event_name}\n"):
            data_line = next(
                line for line in text.splitlines() if line.startswith("data: ")
            )
            return json.loads(data_line[6:])["payload"]
    raise AssertionError(f"missing SSE event {event_name}")


def test_clarification_payload_supports_english_field_labels():
    payload = TravelClarificationService().build_clarification_payload(
        missing_hard=["destination", "duration", "budget"],
        missing_soft=["travelers"],
        response_language="en",
    )

    assert "destination city" in payload["message"]
    assert "trip length" in payload["message"]
    assert "budget range" in payload["message"]
    assert not any("\u4e00" <= char <= "\u9fff" for char in payload["message"])
    assert payload["response_language"] == "en"


@pytest.mark.asyncio
async def test_missing_itinerary_response_is_english(monkeypatch):
    from app.api import travel

    monkeypatch.setattr(
        travel.ConversationService,
        "get_travel_conversation_state",
        AsyncMock(return_value=None),
    )

    response = await travel._build_edit_qa_response(
        request_id="req-missing",
        conversation_id="conv-missing",
        intent="edit",
        intent_detail="edit_day",
        query_text="Change day two",
        user_id=1,
        response_language="en",
    )
    chunks = await _chunks(response.body_iterator)
    payload = _event_payload(chunks, "final_text")

    assert payload["text"].startswith("There is no itinerary")
    assert payload["response_language"] == "en"


@pytest.mark.asyncio
async def test_reset_acknowledgement_is_english(monkeypatch):
    from app.api import travel

    monkeypatch.setattr(
        travel.ConversationService,
        "reset_travel_conversation_state",
        AsyncMock(return_value={}),
    )

    response = await travel._build_reset_response(
        request_id="req-reset",
        conversation_id="conv-reset",
        intent="reset",
        intent_detail="reset_all",
        user_id=1,
        last_user_query="Start over",
        response_language="en",
    )
    chunks = await _chunks(response.body_iterator)
    payload = _event_payload(chunks, "reset_done")

    assert payload["text"].startswith("The itinerary state")
    assert payload["response_language"] == "en"


@pytest.mark.asyncio
async def test_missing_edit_target_response_is_english(monkeypatch):
    from app.api import travel

    monkeypatch.setattr(travel, "parse_edit_ops", lambda *_args: [])
    monkeypatch.setattr(
        travel,
        "build_structured_edit_command",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(travel, "has_mutation_intent", lambda _query: True)

    chunks = await _chunks(
        travel._stream_edit_result(
            utterance="Change the itinerary",
            current_itinerary={"revision_id": "rev-1", "days": []},
            request_id="req-edit",
            conversation_id="conv-edit",
            intent="edit",
            intent_detail="edit_day",
            response_language="en",
        )
    )
    payload = _event_payload(chunks, "final_text")

    assert payload["text"].startswith("Please specify which day")
    assert payload["response_language"] == "en"


@pytest.mark.asyncio
async def test_draft_failure_fallback_is_english(monkeypatch):
    from app.api import travel

    monkeypatch.setattr(
        travel.travel_draft_graph,
        "ainvoke",
        AsyncMock(
            return_value={
                "final_itinerary": None,
                "final_text": None,
                "perf": {},
            }
        ),
    )

    chunks = await _chunks(
        travel._stream_minimal_itinerary(
            query_text="Plan a trip",
            original_query="Plan a trip",
            thread_config={},
            conversation_id="conv-draft",
            request_id="req-draft",
            response_language="en",
        )
    )
    payload = _event_payload(chunks, "final_text")

    assert payload["text"].startswith("I could not generate")
    assert payload["response_language"] == "en"


@pytest.mark.asyncio
async def test_candidate_insufficient_exit_is_english():
    from app.lg_agent.travel_draft_graph import grounding_exit_node

    result = await grounding_exit_node(
        {
            "response_language": "en",
            "grounding_message": None,
            "perf": {},
        }
    )

    assert result["final_text"].startswith("There are not enough verified")


@pytest.mark.asyncio
async def test_duplicate_request_response_is_english():
    from app.api import travel

    response = travel._build_duplicate_request_response(
        request_id="req-duplicate",
        conversation_id="conv-duplicate",
        response_language="en",
    )
    chunks = await _chunks(response.body_iterator)
    payload = _event_payload(chunks, "final_text")

    assert payload["text"].startswith("An identical request is already")
    assert payload["response_language"] == "en"


def test_successful_edit_feedback_is_localized_for_english():
    from app.api import travel

    explanation, summary = travel._localize_edit_feedback(
        explanation="已修改 第2天。第二天下午已重新规划。",
        change_summary={
            "changed_days": [2],
            "diff_items": ["第二天下午已重新规划"],
            "execution_source": "structured_qp",
        },
        response_language="en",
    )

    assert explanation == "Updated day 2. Other days were preserved."
    assert summary["diff_items"] == [
        "Updated day 2 based on the requested constraints."
    ]
    assert summary["execution_source"] == "structured_qp"


@pytest.mark.asyncio
async def test_graph_early_exit_is_english():
    from app.lg_agent.travel_draft_graph import early_exit_node

    result = await early_exit_node(
        {
            "missing_p0": ["目的地", "行程天数"],
            "response_language": "en",
        }
    )

    assert result["final_text"] == (
        "To build a structured itinerary, please provide: "
        "destination and trip length."
    )


@pytest.mark.asyncio
async def test_graph_missing_draft_fallback_is_english():
    from app.lg_agent.travel_draft_graph import postprocess_node

    result = await postprocess_node(
        {
            "itinerary": None,
            "pipeline_result": None,
            "response_language": "en",
            "perf": {},
        }
    )

    assert result["final_text"].startswith("I could not generate")


@pytest.mark.asyncio
async def test_successful_draft_events_expose_english_language_metadata(monkeypatch):
    from app.api import travel

    itinerary = {
        "revision_id": "rev-en",
        "trip_profile": {"destination_city": "Bristol"},
        "days": [
            {
                "day_index": 1,
                "slots": [
                    {
                        "slot": "morning",
                        "activity": "Visit the harbour",
                        "place": "Bristol Harbour",
                    }
                ],
            }
        ],
        "evidence": [{"title": "Bristol Harbour"}],
        "validation": {"coverage_score": 1.0, "assumptions": []},
    }
    monkeypatch.setattr(
        travel.travel_draft_graph,
        "ainvoke",
        AsyncMock(
            return_value={
                "final_itinerary": itinerary,
                "explanation": "A one-day Bristol itinerary.",
                "final_text": None,
                "perf": {},
            }
        ),
    )
    monkeypatch.setattr(
        travel.ConversationService,
        "upsert_travel_conversation_state",
        AsyncMock(return_value={}),
    )

    chunks = await _chunks(
        travel._stream_minimal_itinerary(
            query_text="Plan one day in Bristol",
            thread_config={},
            conversation_id="conv-success-en",
            request_id="req-success-en",
            response_language="en",
        )
    )

    for event_name in (
        "pipeline_complete",
        "tool_result",
        "day_ready",
        "stage_progress",
        "final_itinerary",
    ):
        assert _event_payload(chunks, event_name)["response_language"] == "en"
