from __future__ import annotations

from copy import deepcopy

import pytest

from app.domain.travel.conversation_runtime import (
    ConversationDecisionService,
    ConversationRuntimeSnapshot,
    apply_transition,
)


def _itinerary(destination: str = "深圳", revision_id: str = "rev-1") -> dict:
    return {
        "schema_version": "itinerary.v1",
        "itinerary_id": "itinerary-1",
        "revision_id": revision_id,
        "trip_profile": {
            "destination_city": destination,
            "constraints": {
                "budget_range": "6000",
                "traveler_type": "朋友",
                "preferences": ["美食", "文化"],
            },
        },
        "days": [
            {
                "day_index": 1,
                "slots": [
                    {
                        "slot": "上午",
                        "activity": "参观",
                        "place": f"{destination}博物馆",
                    }
                ],
            }
        ],
        "budget_summary": {"total_estimate": 6000},
    }


def _snapshot(
    *,
    destination: str | None = "深圳",
    revision_id: str | None = "rev-1",
    has_itinerary: bool = True,
) -> ConversationRuntimeSnapshot:
    itinerary = _itinerary(destination or "深圳", revision_id or "rev-1") if has_itinerary else None
    return ConversationRuntimeSnapshot(
        conversation_id="conv-1",
        active_destination=destination,
        trip_profile=(itinerary or {}).get("trip_profile") or {},
        current_itinerary=itinerary,
        current_revision_id=revision_id if has_itinerary else None,
        last_user_query="上一轮",
    )


def _qp(
    *,
    intent: str,
    destination: str | None = None,
    target_day: int | None = None,
    target_slot: str | None = None,
    confidence: float | None = None,
) -> dict:
    return {
        "intent": intent,
        "intent_detail": {
            "create": "first_create",
            "edit": "edit_day",
            "qa": "qa_local",
            "chat": "general_chat",
            "reset": "reset_all",
        }[intent],
        "constraints": {
            "destination_city": destination,
            "days": None,
            "budget": None,
            "traveler_type": None,
            "preferences": [],
            "pace": None,
        },
        "target_day": target_day,
        "target_slot": target_slot,
        "confidence": confidence,
    }


def test_qa_is_always_read_only():
    decision = ConversationDecisionService().decide(
        "第三天下午去哪里",
        _qp(intent="qa", target_day=3, target_slot="下午"),
        _snapshot(),
    )

    assert decision.intent == "qa"
    assert decision.mutation_scope == "none"
    assert decision.target_day == 3
    assert decision.target_slot == "下午"


def test_chat_is_read_only_and_preserves_active_goal():
    snapshot = _snapshot()
    decision = ConversationDecisionService().decide(
        "今天天气真不错",
        _qp(intent="chat"),
        snapshot,
    )
    result = apply_transition(snapshot, decision)

    assert decision.intent == "chat"
    assert decision.mutation_scope == "none"
    assert result.state_after.active_destination == "深圳"
    assert result.state_after.current_revision_id == "rev-1"
    assert result.revision_changed is False


def test_pending_clarification_reclassifies_flexible_chat_reply():
    snapshot = _snapshot(destination=None, revision_id=None, has_itinerary=False)
    snapshot.pending_clarification = {
        "values": {
            "destination": "香港",
            "duration": None,
            "budget": None,
            "travelers": None,
        }
    }

    decision = ConversationDecisionService().decide(
        "都可以",
        _qp(intent="chat"),
        snapshot,
    )

    assert decision.intent == "clarify"
    assert decision.mutation_scope == "constraints_only"
    assert decision.reason == "pending_clarification_reply"


@pytest.mark.parametrize(
    ("query", "incoming"),
    [
        ("还是改去杭州吧", "杭州"),
        ("不去深圳了，换成厦门", "厦门"),
        ("change the destination to Hangzhou", "Hangzhou"),
        ("let's go to Xiamen instead", "Xiamen"),
        ("Let's switch the trip to Oaxaca", "Oaxaca"),
    ],
)
def test_destination_switch_requires_explicit_replacement(query: str, incoming: str):
    decision = ConversationDecisionService().decide(
        query,
        _qp(intent="create", destination=incoming, confidence=0.92),
        _snapshot(),
    )

    assert decision.intent == "change_destination"
    assert decision.destination == incoming
    assert decision.mutation_scope == "whole_trip"
    assert decision.preserve_fields == [
        "duration",
        "budget",
        "traveler_type",
        "preferences",
        "pace",
    ]
    assert "current_itinerary" in decision.clear_fields
    assert "current_revision_id" in decision.clear_fields


@pytest.mark.parametrize(
    ("query", "incoming"),
    [
        ("深圳到香港怎么走", "香港"),
        ("香港和澳门哪个更适合", "澳门"),
        ("How do I get from Shenzhen to Hong Kong?", "Hong Kong"),
        ("Is Macau better than Hong Kong?", "Macau"),
    ],
)
def test_city_mention_without_replacement_is_read_only(query: str, incoming: str):
    decision = ConversationDecisionService().decide(
        query,
        _qp(intent="create", destination=incoming),
        _snapshot(),
    )

    assert decision.intent == "qa"
    assert decision.mutation_scope == "none"
    assert decision.destination == "深圳"


def test_same_destination_with_switch_words_is_not_a_destination_change():
    decision = ConversationDecisionService().decide(
        "还是去深圳吧",
        _qp(intent="create", destination="深圳"),
        _snapshot(),
    )

    assert decision.intent != "change_destination"


def test_slot_edit_and_day_edit_have_distinct_mutation_scopes():
    service = ConversationDecisionService()

    slot = service.decide(
        "把第二天下午改成室内",
        _qp(intent="edit", target_day=2, target_slot="下午"),
        _snapshot(),
    )
    day = service.decide(
        "把第二天改轻松一点",
        _qp(intent="edit", target_day=2),
        _snapshot(),
    )

    assert slot.mutation_scope == "single_slot"
    assert day.mutation_scope == "single_day"


def test_destination_transition_clears_active_stale_itinerary_without_mutating_input():
    snapshot = _snapshot()
    original = deepcopy(snapshot.model_dump())
    decision = ConversationDecisionService().decide(
        "还是改去杭州吧",
        _qp(intent="create", destination="杭州"),
        snapshot,
    )

    result = apply_transition(snapshot, decision)

    assert snapshot.model_dump() == original
    assert result.state_after.active_destination == "杭州"
    assert result.state_after.current_itinerary is None
    assert result.state_after.current_revision_id is None
    assert result.state_after.pending_clarification is None
    assert result.revision_changed is True


def test_read_only_transition_preserves_itinerary_and_revision():
    snapshot = _snapshot()
    decision = ConversationDecisionService().decide(
        "第三天下午去哪里",
        _qp(intent="qa", target_day=3, target_slot="下午"),
        snapshot,
    )

    result = apply_transition(snapshot, decision)

    assert result.state_after.current_itinerary == snapshot.current_itinerary
    assert result.state_after.current_revision_id == "rev-1"
    assert result.revision_changed is False


def test_read_only_transition_preserves_response_language():
    snapshot = ConversationRuntimeSnapshot(
        conversation_id="conv-language",
        active_destination="深圳",
        response_language="zh-CN",
    )
    decision = ConversationDecisionService().decide(
        "第三天下午去哪里",
        _qp(intent="qa", target_day=3, target_slot="下午"),
        snapshot,
    )

    result = apply_transition(snapshot, decision)

    assert snapshot.response_language == "zh-CN"
    assert result.state_after.response_language == "zh-CN"


def test_edit_preview_does_not_commit_a_revision():
    snapshot = _snapshot()
    decision = ConversationDecisionService().decide(
        "把第二天改轻松一点",
        _qp(intent="edit", target_day=2),
        snapshot,
    )

    result = apply_transition(snapshot, decision)

    assert result.state_after.current_revision_id == "rev-1"
    assert result.revision_changed is False


def test_reset_clears_active_runtime_state():
    snapshot = _snapshot()
    snapshot.pending_clarification = {"values": {"destination": "深圳"}}
    decision = ConversationDecisionService().decide(
        "重新开始",
        _qp(intent="reset"),
        snapshot,
    )

    result = apply_transition(snapshot, decision)

    assert decision.mutation_scope == "reset_all"
    assert result.state_after.active_destination is None
    assert result.state_after.current_itinerary is None
    assert result.state_after.current_revision_id is None
    assert result.state_after.pending_clarification is None
    assert result.revision_changed is True
