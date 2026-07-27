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
