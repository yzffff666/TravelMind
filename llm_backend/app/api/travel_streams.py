from __future__ import annotations

from typing import Any

from app.domain.travel.rules import TRAVEL_API_RULES
from app.domain.travel.sse_envelope import (
    build_data_line,
    build_event_envelope,
    build_event_line,
)
from app.lg_agent.travel_draft_graph import travel_draft_graph
from app.services.conversation_service import ConversationService


class TravelStreamService:
    """Encapsulates travel SSE event streaming and itinerary generation streams."""

    def __init__(self, *, clarification_service: Any, logger: Any):
        self._clarification_service = clarification_service
        self._logger = logger

    @staticmethod
    def _build_sse_line(payload: object) -> str:
        return build_data_line(payload)

    async def stream_intent_routed_event(
        self,
        *,
        request_id: str,
        conversation_id: str,
        intent: str,
        intent_detail: str,
    ):
        yield build_event_line(
            TRAVEL_API_RULES.event_intent_routed,
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=None,
                payload={"intent": intent, "intent_detail": intent_detail},
            ),
        )

    async def stream_intent_text_response(
        self,
        *,
        request_id: str,
        conversation_id: str,
        intent: str,
        intent_detail: str,
        text: str,
        event_name: str = TRAVEL_API_RULES.event_final_text,
    ):
        async for line in self.stream_intent_routed_event(
            request_id=request_id,
            conversation_id=conversation_id,
            intent=intent,
            intent_detail=intent_detail,
        ):
            yield line
        yield build_event_line(
            event_name,
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=None,
                payload={"text": text},
            ),
        )
        yield self._build_sse_line(text)

    async def stream_intent_itinerary_response(
        self,
        *,
        request_id: str,
        conversation_id: str,
        intent: str,
        intent_detail: str,
        itinerary: dict,
        explanation: str,
    ):
        async for line in self.stream_intent_routed_event(
            request_id=request_id,
            conversation_id=conversation_id,
            intent=intent,
            intent_detail=intent_detail,
        ):
            yield line
        yield build_event_line(
            TRAVEL_API_RULES.event_final_itinerary,
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=itinerary.get("revision_id"),
                payload={"itinerary": itinerary, "explanation": explanation},
            ),
        )
        yield self._build_sse_line(explanation)

    async def stream_clarification_events(
        self,
        *,
        request_id: str,
        conversation_id: str,
        missing_hard: list[str],
        missing_soft: list[str],
    ):
        clarification_payload = self._clarification_service.build_clarification_payload(
            missing_hard=missing_hard,
            missing_soft=missing_soft,
        )
        yield build_event_line(
            TRAVEL_API_RULES.event_stage_start,
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=None,
                payload={"stage": clarification_payload["stage"]},
            ),
        )
        yield build_event_line(
            TRAVEL_API_RULES.event_stage_progress,
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=None,
                payload=clarification_payload,
            ),
        )
        yield self._build_sse_line(clarification_payload["message"])

    async def stream_minimal_itinerary(
        self,
        *,
        query_text: str,
        thread_config: dict,
        conversation_id: str,
        request_id: str,
        user_id: int | None = None,
    ):
        try:
            result = await travel_draft_graph.ainvoke(
                input={"query": query_text},
                config=thread_config,
            )
            final_itinerary = result.get("final_itinerary")
            explanation = result.get("explanation")
            final_text = result.get("final_text")

            if not final_itinerary:
                fallback_text = final_text or TRAVEL_API_RULES.text_generate_fallback
                yield build_event_line(
                    TRAVEL_API_RULES.event_final_text,
                    build_event_envelope(
                        request_id=request_id,
                        conversation_id=conversation_id,
                        revision_id=None,
                        payload={"text": fallback_text},
                    ),
                )
                yield self._build_sse_line(fallback_text)
                return

            yield build_event_line(
                TRAVEL_API_RULES.event_final_itinerary,
                build_event_envelope(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=final_itinerary.get("revision_id"),
                    payload={
                        "itinerary": final_itinerary,
                        "explanation": explanation or "",
                    },
                ),
            )
            try:
                await ConversationService.upsert_travel_conversation_state(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    current_revision_id=final_itinerary.get("revision_id"),
                    trip_profile=final_itinerary.get("trip_profile"),
                    current_itinerary=final_itinerary,
                    last_user_query=query_text,
                )
            except Exception as persist_error:
                self._logger.error(
                    f"Persist travel conversation state failed: {str(persist_error)}",
                    exc_info=True,
                )
            if explanation:
                yield self._build_sse_line(explanation)
        except Exception as exc:
            self._logger.error(f"Generate travel draft failed: {str(exc)}", exc_info=True)
            yield build_event_line(
                TRAVEL_API_RULES.event_error,
                build_event_envelope(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=None,
                    payload={"text": TRAVEL_API_RULES.text_generate_error},
                ),
            )
            yield self._build_sse_line(TRAVEL_API_RULES.text_generate_error)
