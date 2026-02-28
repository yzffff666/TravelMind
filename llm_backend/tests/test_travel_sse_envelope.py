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

