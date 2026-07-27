"""Conversation-level routing and state-transition contracts.

The query processor classifies one utterance. This module combines that result
with the active itinerary state and decides whether the turn may mutate state.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


ConversationIntent = Literal[
    "create",
    "clarify",
    "qa",
    "edit",
    "change_destination",
    "chat",
    "reset",
]
MutationScope = Literal[
    "none",
    "constraints_only",
    "single_slot",
    "single_day",
    "whole_trip",
    "reset_all",
]

_DESTINATION_REPLACEMENT_PATTERN = re.compile(
    r"(?:"
    r"改\s*(?:去|成|为)|"
    r"换\s*(?:去|成|为)|"
    r"不去.+?(?:去|换成|改去)|"
    r"还是\s*(?:改去|换去|去)|"
    r"change\s+(?:the\s+)?destination\s+to|"
    r"(?:go|travel)\s+to.+\s+instead|"
    r"let['’]?s\s+go\s+to.+\s+instead"
    r")",
    re.IGNORECASE,
)
_READ_ONLY_QUESTION_PATTERN = re.compile(
    r"(?:[?？]|怎么|如何|哪个|哪一个|是否|合适吗|好吗|吗$|"
    r"\bhow\b|\bwhich\b|\bis\b|\bare\b|\bwhat\b|\bbetter\b)",
    re.IGNORECASE,
)

_PORTABLE_CONSTRAINTS = [
    "duration",
    "budget",
    "traveler_type",
    "preferences",
    "pace",
]
_DESTINATION_CLEAR_FIELDS = [
    "current_itinerary",
    "current_revision_id",
    "pending_clarification",
    "destination_candidates",
]


class ConversationDecision(BaseModel):
    intent: ConversationIntent
    intent_detail: str
    confidence: float | None = None
    destination: str | None = None
    target_day: int | None = None
    target_slot: str | None = None
    mutation_scope: MutationScope
    preserve_fields: list[str] = Field(default_factory=list)
    clear_fields: list[str] = Field(default_factory=list)
    reason: str


class ConversationRuntimeSnapshot(BaseModel):
    conversation_id: str
    active_destination: str | None = None
    trip_profile: dict[str, Any] = Field(default_factory=dict)
    current_itinerary: dict[str, Any] | None = None
    current_revision_id: str | None = None
    pending_clarification: dict[str, Any] | None = None
    asked_fields: list[str] = Field(default_factory=list)
    last_decision: dict[str, Any] | None = None
    last_user_query: str | None = None

    @property
    def has_itinerary(self) -> bool:
        return bool(self.current_itinerary)


class ConversationTransitionResult(BaseModel):
    decision: ConversationDecision
    state_before: ConversationRuntimeSnapshot
    state_after: ConversationRuntimeSnapshot
    revision_changed: bool = False
    blocked: bool = False
    block_reason: str | None = None


class ConversationDecisionService:
    """Derive the final conversation action from QP output and active state."""

    def decide(
        self,
        query: str,
        qp_output: dict[str, Any],
        snapshot: ConversationRuntimeSnapshot,
    ) -> ConversationDecision:
        qp_intent = str(qp_output.get("intent") or "chat")
        intent_detail = str(qp_output.get("intent_detail") or "general_chat")
        constraints = dict(qp_output.get("constraints") or {})
        incoming_destination = _clean_text(constraints.get("destination_city"))
        active_destination = _clean_text(snapshot.active_destination)
        target_day = _as_positive_int(qp_output.get("target_day"))
        target_slot = _clean_text(qp_output.get("target_slot"))
        confidence = _as_confidence(qp_output.get("confidence"))

        if qp_intent == "reset":
            return ConversationDecision(
                intent="reset",
                intent_detail=intent_detail,
                confidence=confidence,
                destination=None,
                mutation_scope="reset_all",
                clear_fields=[
                    "active_destination",
                    "current_itinerary",
                    "current_revision_id",
                    "pending_clarification",
                    "dialogue_state",
                ],
                reason="explicit_reset",
            )

        if (
            snapshot.has_itinerary
            and incoming_destination
            and not _same_destination(incoming_destination, active_destination)
            and _DESTINATION_REPLACEMENT_PATTERN.search(query or "")
        ):
            return ConversationDecision(
                intent="change_destination",
                intent_detail="change_destination",
                confidence=confidence,
                destination=incoming_destination,
                mutation_scope="whole_trip",
                preserve_fields=list(_PORTABLE_CONSTRAINTS),
                clear_fields=list(_DESTINATION_CLEAR_FIELDS),
                reason="explicit_destination_replacement",
            )

        if qp_intent == "qa" or (
            snapshot.has_itinerary
            and incoming_destination
            and not _same_destination(incoming_destination, active_destination)
            and _READ_ONLY_QUESTION_PATTERN.search(query or "")
        ):
            return ConversationDecision(
                intent="qa",
                intent_detail="qa_local" if qp_intent != "qa" else intent_detail,
                confidence=confidence,
                destination=active_destination,
                target_day=target_day,
                target_slot=target_slot,
                mutation_scope="none",
                reason="read_only_question",
            )

        if qp_intent == "chat":
            return ConversationDecision(
                intent="chat",
                intent_detail=intent_detail,
                confidence=confidence,
                destination=active_destination,
                mutation_scope="none",
                reason="casual_chat",
            )

        if qp_intent == "edit":
            return ConversationDecision(
                intent="edit",
                intent_detail=intent_detail,
                confidence=confidence,
                destination=active_destination,
                target_day=target_day,
                target_slot=target_slot,
                mutation_scope="single_slot" if target_slot else "single_day",
                reason="explicit_itinerary_edit",
            )

        return ConversationDecision(
            intent="create",
            intent_detail=intent_detail,
            confidence=confidence,
            destination=incoming_destination or active_destination,
            mutation_scope="whole_trip",
            reason="create_or_replace_plan",
        )


def apply_transition(
    snapshot: ConversationRuntimeSnapshot,
    decision: ConversationDecision,
) -> ConversationTransitionResult:
    """Preview the state transition without mutating the input snapshot."""
    state_before = snapshot.model_copy(deep=True)
    state_after = snapshot.model_copy(deep=True)
    state_after.last_decision = decision.model_dump(mode="json")

    if decision.intent == "change_destination":
        state_after.active_destination = decision.destination
        state_after.trip_profile = {
            **state_after.trip_profile,
            "destination_city": decision.destination,
        }
        state_after.current_itinerary = None
        state_after.current_revision_id = None
        state_after.pending_clarification = None
        state_after.asked_fields = []
    elif decision.intent == "reset":
        state_after.active_destination = None
        state_after.trip_profile = {}
        state_after.current_itinerary = None
        state_after.current_revision_id = None
        state_after.pending_clarification = None
        state_after.asked_fields = []

    revision_changed = state_before.current_revision_id != state_after.current_revision_id
    return ConversationTransitionResult(
        decision=decision,
        state_before=state_before,
        state_after=state_after,
        revision_changed=revision_changed,
    )


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_destination(value: str | None) -> str:
    return re.sub(r"[\s市县区州省]+$", "", (value or "").strip().casefold())


def _same_destination(left: str | None, right: str | None) -> bool:
    left_normalized = _normalize_destination(left)
    right_normalized = _normalize_destination(right)
    return bool(left_normalized and left_normalized == right_normalized)


def _as_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_confidence(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, parsed))
