from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.travel_conversation_state import TravelConversationState
from app.services import conversation_service as conversation_module
from app.services.conversation_service import ConversationService


class _FakeResult:
    def __init__(self, state):
        self._state = state

    def scalar_one_or_none(self):
        return self._state


class _FakeSession:
    def __init__(self, state):
        self.state = state
        self.added = None
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _statement):
        return _FakeResult(self.state)

    def add(self, state):
        self.added = state
        self.state = state

    async def commit(self):
        self.committed = True

    async def refresh(self, _state):
        return None


def _state() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        conversation_id="conv-1",
        user_id=1,
        current_revision_id="rev-1",
        trip_profile_json={"destination_city": "深圳"},
        current_itinerary_json={"revision_id": "rev-1"},
        dialogue_state_json={
            "pending_clarification": {"values": {"destination": "深圳"}},
            "asked_fields": ["duration", "budget"],
        },
        chat_history_json=[],
        chat_summary=None,
        last_user_query="我想去深圳",
        created_at=now,
        updated_at=now,
    )


def _patch_session(monkeypatch: pytest.MonkeyPatch, state):
    fake = _FakeSession(state)
    monkeypatch.setattr(conversation_module, "AsyncSessionLocal", lambda: fake)
    monkeypatch.setattr(
        ConversationService,
        "_ensure_travel_state_table",
        AsyncMock(return_value=None),
    )
    return fake


def test_travel_conversation_state_has_dialogue_state_column():
    assert "dialogue_state_json" in TravelConversationState.__table__.columns


@pytest.mark.asyncio
async def test_get_travel_state_returns_dialogue_state(monkeypatch):
    _patch_session(monkeypatch, _state())

    result = await ConversationService.get_travel_conversation_state("conv-1")

    assert result is not None
    assert result["dialogue_state"]["asked_fields"] == ["duration", "budget"]
    assert result["dialogue_state"]["pending_clarification"]["values"]["destination"] == "深圳"


@pytest.mark.asyncio
async def test_upsert_updates_dialogue_state_without_replacing_itinerary(monkeypatch):
    state = _state()
    fake = _patch_session(monkeypatch, state)
    updated_dialogue = {
        "pending_clarification": None,
        "asked_fields": [],
        "last_decision": {"intent": "qa", "mutation_scope": "none"},
    }

    result = await ConversationService.upsert_travel_conversation_state(
        conversation_id="conv-1",
        dialogue_state=updated_dialogue,
    )

    assert fake.committed is True
    assert state.dialogue_state_json == updated_dialogue
    assert state.current_itinerary_json == {"revision_id": "rev-1"}
    assert result["dialogue_state"] == updated_dialogue


@pytest.mark.asyncio
async def test_update_dialogue_state_has_a_focused_write_api(monkeypatch):
    state = _state()
    fake = _patch_session(monkeypatch, state)
    updated_dialogue = {
        "pending_clarification": {"values": {"destination": "香港"}},
        "asked_fields": ["duration"],
    }

    result = await ConversationService.update_dialogue_state(
        conversation_id="conv-1",
        dialogue_state=updated_dialogue,
    )

    assert fake.committed is True
    assert result["dialogue_state"] == updated_dialogue
    assert state.current_revision_id == "rev-1"


@pytest.mark.asyncio
async def test_reset_clears_dialogue_state(monkeypatch):
    state = _state()
    _patch_session(monkeypatch, state)

    result = await ConversationService.reset_travel_conversation_state(
        conversation_id="conv-1",
        last_user_query="重新开始",
    )

    assert state.dialogue_state_json is None
    assert result["dialogue_state"] is None


def test_destination_switch_runtime_preserves_portable_constraints_and_clears_revision():
    from app.api.travel import (
        _build_destination_change_query,
        _conversation_snapshot_from_state,
        _resolve_conversation_transition,
    )

    state = {
        "current_revision_id": "rev-shenzhen-1",
        "trip_profile": {
            "destination_city": "深圳",
            "travelers": "朋友",
            "constraints": {
                "budget_range": "约 6000 元",
                "traveler_type": "朋友",
                "preferences": ["美食", "文化"],
            },
        },
        "current_itinerary": {
            "revision_id": "rev-shenzhen-1",
            "trip_profile": {"destination_city": "深圳"},
            "days": [{"day_index": 1}, {"day_index": 2}, {"day_index": 3}],
            "budget_summary": {"total_estimate": 6000},
        },
        "dialogue_state": None,
        "last_user_query": "深圳三天",
    }

    transition = _resolve_conversation_transition(
        conversation_id="conv-switch",
        query="还是改去杭州吧",
        qp_output={
            "intent": "create",
            "intent_detail": "first_create",
            "constraints": {"destination_city": "杭州"},
        },
        state=state,
    )
    query = _build_destination_change_query("杭州", state)

    assert transition.decision.intent == "change_destination"
    assert transition.state_after.active_destination == "杭州"
    assert transition.state_after.current_itinerary is None
    assert transition.state_after.current_revision_id is None
    assert "杭州" in query
    assert "3天" in query
    assert "6000" in query
    assert "朋友" in query
    assert "美食" in query
    assert "深圳" not in query


def test_other_city_question_is_read_only_at_runtime_boundary():
    from app.api.travel import _resolve_conversation_transition

    itinerary = {"revision_id": "rev-1", "trip_profile": {"destination_city": "深圳"}}
    state = {
        "current_revision_id": "rev-1",
        "trip_profile": itinerary["trip_profile"],
        "current_itinerary": itinerary,
        "dialogue_state": None,
    }

    transition = _resolve_conversation_transition(
        conversation_id="conv-readonly",
        query="深圳到香港怎么走？",
        qp_output={
            "intent": "create",
            "intent_detail": "first_create",
            "constraints": {"destination_city": "香港"},
        },
        state=state,
    )

    assert transition.decision.intent == "qa"
    assert transition.decision.mutation_scope == "none"
    assert transition.state_after.current_itinerary == itinerary
    assert transition.state_after.current_revision_id == "rev-1"


@pytest.mark.asyncio
async def test_loading_runtime_restores_persisted_clarification(monkeypatch):
    from app.api import travel

    persisted_pending = {
        "initial_query": "我想去香港",
        "values": {
            "destination": "香港",
            "duration": None,
            "budget": None,
            "travelers": None,
        },
        "followups": [],
        "asked_fields": ["duration", "budget"],
        "assumptions": [],
    }

    async def fake_get_state(conversation_id: str):
        assert conversation_id == "conv-restore"
        return {
            "current_revision_id": None,
            "trip_profile": None,
            "current_itinerary": None,
            "dialogue_state": {
                "pending_clarification": persisted_pending,
                "asked_fields": ["duration", "budget"],
            },
            "last_user_query": "我想去香港",
        }

    monkeypatch.setattr(
        travel.ConversationService,
        "get_travel_conversation_state",
        fake_get_state,
    )
    travel.clarification_service.clear_pending("conv-restore")

    state, snapshot = await travel._load_conversation_runtime("conv-restore")

    assert state is not None
    assert snapshot.pending_clarification == persisted_pending
    assert travel.clarification_service.has_pending("conv-restore")


@pytest.mark.asyncio
async def test_replace_runtime_state_can_explicitly_clear_old_revision(monkeypatch):
    state = _state()
    fake = _patch_session(monkeypatch, state)

    result = await ConversationService.replace_travel_conversation_runtime(
        conversation_id="conv-1",
        user_id=1,
        current_revision_id=None,
        trip_profile={"destination_city": "杭州"},
        current_itinerary=None,
        dialogue_state={
            "active_destination": "杭州",
            "pending_clarification": None,
            "asked_fields": [],
        },
        last_user_query="还是改去杭州吧",
    )

    assert fake.committed is True
    assert state.current_revision_id is None
    assert state.current_itinerary_json is None
    assert state.trip_profile_json["destination_city"] == "杭州"
    assert result["dialogue_state"]["active_destination"] == "杭州"


def _api_state(
    destination: str = "深圳",
    revision_id: str = "rev-1",
    *,
    dialogue_state: dict | None = None,
) -> dict:
    itinerary = {
        "revision_id": revision_id,
        "trip_profile": {
            "destination_city": destination,
            "constraints": {
                "budget_range": "6000",
                "traveler_type": "朋友",
                "preferences": ["美食"],
            },
        },
        "days": [
            {
                "day_index": index,
                "slots": [
                    {
                        "slot": "上午",
                        "activity": f"{destination}第{index}天活动",
                        "place": f"{destination}景点{index}",
                    }
                ],
            }
            for index in range(1, 4)
        ],
        "budget_summary": {"total_estimate": 6000},
    }
    return {
        "conversation_id": "conv-api",
        "user_id": 1,
        "current_revision_id": revision_id,
        "trip_profile": itinerary["trip_profile"],
        "current_itinerary": itinerary,
        "dialogue_state": dialogue_state,
        "last_user_query": f"{destination}三天",
    }


def _qp_result(
    *,
    intent: str,
    destination: str | None = None,
    target_day: int | None = None,
    target_slot: str | None = None,
) -> dict:
    return {
        "intent": intent,
        "intent_detail": {
            "create": "first_create",
            "edit": "edit_day",
            "qa": "qa_local",
            "chat": "general_chat",
        }[intent],
        "normalized_query": destination or "都可以",
        "recall_query": destination or "都可以",
        "constraints": {"destination_city": destination},
        "missing_required": [],
        "qp_source": "rule",
        "confidence": None,
        "fallback_reason": None,
        "structured_qp_mode": "off",
        "route_reason": "test",
        "safety_level": "safe",
        "shadow_intent": None,
        "target_day": target_day,
        "target_slot": target_slot,
    }


async def _consume_response(response) -> list[str]:
    return [chunk async for chunk in response.body_iterator]


@pytest.mark.asyncio
async def test_query_endpoint_switches_destination_with_portable_constraints(monkeypatch):
    from app.api import travel

    state = _api_state()
    replacements: list[dict] = []
    generated: list[dict] = []

    async def fake_ensure_user(_user_id: int):
        return None

    async def fake_get_state(_conversation_id: str):
        return state

    async def fake_upsert(**kwargs):
        return kwargs

    async def fake_update_dialogue_state(**kwargs):
        state["dialogue_state"] = kwargs["dialogue_state"]
        return state

    async def fake_replace(**kwargs):
        replacements.append(kwargs)
        state.update(
            current_revision_id=kwargs["current_revision_id"],
            trip_profile=kwargs["trip_profile"],
            current_itinerary=kwargs["current_itinerary"],
            dialogue_state=kwargs["dialogue_state"],
        )
        return state

    async def fake_process(query: str, _conversation_id: str):
        if query == "还是改去杭州吧":
            return _qp_result(intent="create", destination="杭州")
        assert "杭州" in query and "3天" in query and "6000" in query
        return {
            **_qp_result(intent="create", destination="杭州"),
            "normalized_query": query,
            "recall_query": query,
        }

    async def fake_stream(**kwargs):
        generated.append(kwargs)
        yield "data: \"done\"\n\n"

    monkeypatch.setattr(travel, "_ensure_user_exists", fake_ensure_user)
    monkeypatch.setattr(travel.ConversationService, "get_travel_conversation_state", fake_get_state)
    monkeypatch.setattr(travel.ConversationService, "upsert_travel_conversation_state", fake_upsert)
    monkeypatch.setattr(travel.ConversationService, "update_dialogue_state", fake_update_dialogue_state)
    monkeypatch.setattr(travel.ConversationService, "replace_travel_conversation_runtime", fake_replace)
    monkeypatch.setattr(travel, "_process_qp", fake_process)
    monkeypatch.setattr(travel, "_stream_minimal_itinerary", fake_stream)
    travel.clarification_service.clear_pending("conv-switch-api")
    travel._active_request_fingerprints.clear()

    response = await travel.langgraph_query(
        query="还是改去杭州吧",
        user_id=1,
        conversation_id="conv-switch-api",
        image=None,
    )
    await _consume_response(response)

    assert replacements
    assert replacements[0]["current_revision_id"] is None
    assert replacements[0]["current_itinerary"] is None
    assert replacements[0]["trip_profile"]["destination_city"] == "杭州"
    assert "杭州" in generated[0]["original_query"]
    assert "深圳" not in generated[0]["original_query"]


@pytest.mark.asyncio
async def test_query_endpoint_other_city_question_never_enters_edit_or_replace(monkeypatch):
    from app.api import travel

    state = _api_state()
    replaced = False
    edit_called = False

    async def fake_ensure_user(_user_id: int):
        return None

    async def fake_get_state(_conversation_id: str):
        return state

    async def fake_upsert(**kwargs):
        return kwargs

    async def fake_process(_query: str, _conversation_id: str):
        return _qp_result(intent="create", destination="香港")

    async def fail_replace(**_kwargs):
        nonlocal replaced
        replaced = True

    async def fake_edit_qa(**kwargs):
        nonlocal edit_called
        edit_called = kwargs["intent"] == "edit"
        return StreamingResponse(iter(["data: \"qa\"\n\n"]), media_type="text/event-stream")

    from fastapi.responses import StreamingResponse

    monkeypatch.setattr(travel, "_ensure_user_exists", fake_ensure_user)
    monkeypatch.setattr(travel.ConversationService, "get_travel_conversation_state", fake_get_state)
    monkeypatch.setattr(travel.ConversationService, "upsert_travel_conversation_state", fake_upsert)
    monkeypatch.setattr(travel.ConversationService, "replace_travel_conversation_runtime", fail_replace)
    monkeypatch.setattr(travel, "_process_qp", fake_process)
    monkeypatch.setattr(travel, "_build_edit_qa_response", fake_edit_qa)
    travel.clarification_service.clear_pending("conv-qa-city")
    travel._active_request_fingerprints.clear()

    response = await travel.langgraph_query(
        query="深圳到香港怎么走？",
        user_id=1,
        conversation_id="conv-qa-city",
        image=None,
    )
    await _consume_response(response)

    assert replaced is False
    assert edit_called is False
    assert state["current_revision_id"] == "rev-1"


@pytest.mark.asyncio
async def test_query_endpoint_restores_pending_clarification_before_routing(monkeypatch):
    from app.api import travel

    pending = {
        "initial_query": "我想去香港",
        "values": {
            "destination": "香港",
            "duration": None,
            "budget": None,
            "travelers": None,
        },
        "followups": [],
        "asked_fields": ["duration", "budget"],
        "assumptions": [],
    }
    state = {
        "conversation_id": "conv-pending-api",
        "user_id": 1,
        "current_revision_id": None,
        "trip_profile": None,
        "current_itinerary": None,
        "dialogue_state": {
            "pending_clarification": pending,
            "asked_fields": ["duration", "budget"],
        },
        "last_user_query": "我想去香港",
    }
    persisted_dialogue: list[dict] = []
    generated: list[dict] = []

    async def fake_ensure_user(_user_id: int):
        return None

    async def fake_get_state(_conversation_id: str):
        return state

    async def fake_upsert(**kwargs):
        if kwargs.get("dialogue_state") is not None:
            state["dialogue_state"] = kwargs["dialogue_state"]
        return state

    async def fake_update_dialogue_state(**kwargs):
        persisted_dialogue.append(kwargs["dialogue_state"])
        state["dialogue_state"] = kwargs["dialogue_state"]
        return state

    async def fake_process(query: str, _conversation_id: str):
        if query == "都可以":
            return _qp_result(intent="chat")
        return {
            **_qp_result(intent="create", destination="香港"),
            "normalized_query": query,
            "recall_query": query,
        }

    async def fake_stream(**kwargs):
        generated.append(kwargs)
        yield "data: \"done\"\n\n"

    monkeypatch.setattr(travel, "_ensure_user_exists", fake_ensure_user)
    monkeypatch.setattr(travel.ConversationService, "get_travel_conversation_state", fake_get_state)
    monkeypatch.setattr(travel.ConversationService, "upsert_travel_conversation_state", fake_upsert)
    monkeypatch.setattr(travel.ConversationService, "update_dialogue_state", fake_update_dialogue_state)
    monkeypatch.setattr(travel, "_process_qp", fake_process)
    monkeypatch.setattr(travel, "_stream_minimal_itinerary", fake_stream)
    travel.clarification_service.clear_pending("conv-pending-api")
    travel._active_request_fingerprints.clear()

    response = await travel.langgraph_query(
        query="都可以",
        user_id=1,
        conversation_id="conv-pending-api",
        image=None,
    )
    await _consume_response(response)

    assert generated
    assert "香港" in generated[0]["original_query"]
    assert "3天" in generated[0]["original_query"]
    assert "6000" in generated[0]["original_query"]
    assert persisted_dialogue[-1]["pending_clarification"] is None


@pytest.mark.asyncio
async def test_query_endpoint_consecutive_edits_read_latest_committed_revision(monkeypatch):
    from app.api import travel
    from fastapi.responses import StreamingResponse

    state = _api_state()
    seen_revisions: list[str] = []

    async def fake_ensure_user(_user_id: int):
        return None

    async def fake_get_state(_conversation_id: str):
        return state

    async def fake_upsert(**kwargs):
        if kwargs.get("dialogue_state") is not None:
            state["dialogue_state"] = kwargs["dialogue_state"]
        return state

    async def fake_process(query: str, _conversation_id: str):
        target_day = 2 if "第二天" in query else 3
        return _qp_result(intent="edit", target_day=target_day)

    async def fake_edit_qa(**kwargs):
        seen_revisions.append(state["current_revision_id"])
        next_revision = f"rev-{len(seen_revisions) + 1}"
        state["current_revision_id"] = next_revision
        state["current_itinerary"]["revision_id"] = next_revision
        return StreamingResponse(iter(["data: \"edited\"\n\n"]), media_type="text/event-stream")

    monkeypatch.setattr(travel, "_ensure_user_exists", fake_ensure_user)
    monkeypatch.setattr(travel.ConversationService, "get_travel_conversation_state", fake_get_state)
    monkeypatch.setattr(travel.ConversationService, "upsert_travel_conversation_state", fake_upsert)
    monkeypatch.setattr(travel, "_process_qp", fake_process)
    monkeypatch.setattr(travel, "_build_edit_qa_response", fake_edit_qa)
    travel.clarification_service.clear_pending("conv-edits-api")
    travel._active_request_fingerprints.clear()

    first = await travel.langgraph_query(
        query="把第二天改轻松一点",
        user_id=1,
        conversation_id="conv-edits-api",
        image=None,
    )
    await _consume_response(first)
    second = await travel.langgraph_query(
        query="把第三天改成室内",
        user_id=1,
        conversation_id="conv-edits-api",
        image=None,
    )
    await _consume_response(second)

    assert seen_revisions == ["rev-1", "rev-2"]
    assert state["current_revision_id"] == "rev-3"
