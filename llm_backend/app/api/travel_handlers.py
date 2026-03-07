from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from fastapi.responses import StreamingResponse

from app.domain.travel.rules import TRAVEL_API_RULES
from app.lg_agent.utils import new_uuid
from app.services.conversation_service import ConversationService


class TravelRequestHandler:
    """Reusable request-flow handler for travel query/resume routes."""

    def __init__(
        self,
        *,
        query_processor: Any,
        patch_engine: Any,
        clarification_service: Any,
        stream_service: Any,
        logger: Any,
    ):
        self._query_processor = query_processor
        self._patch_engine = patch_engine
        self._clarification_service = clarification_service
        self._stream_service = stream_service
        self._logger = logger

    @staticmethod
    def stream_response(generator, *, conversation_id: str) -> StreamingResponse:
        response = StreamingResponse(generator, media_type="text/event-stream")
        response.headers["X-Conversation-ID"] = conversation_id
        return response

    @staticmethod
    def build_thread_config(*, thread_id: str, user_id: int, image_path: Path | None = None) -> dict:
        return {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
                "image_path": str(image_path) if image_path else None,
            }
        }

    async def save_uploaded_image(
        self,
        *,
        image: UploadFile,
        conversation_id: str | None = None,
    ) -> tuple[Path, str, int]:
        image_dir = Path(TRAVEL_API_RULES.upload_image_root)
        if conversation_id:
            image_dir = image_dir / conversation_id
        image_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime(TRAVEL_API_RULES.upload_timestamp_format)
        original_name, ext = os.path.splitext(image.filename)
        new_filename = f"{original_name}_{timestamp}{ext}"
        image_path = image_dir / new_filename

        content = await image.read()
        with open(image_path, "wb") as file_stream:
            file_stream.write(content)
        return image_path, timestamp, len(content)

    def parse_qp(self, *, query_text: str, thread_id: str) -> dict[str, Any]:
        qp_output = self._query_processor.process(query_text)
        self._logger.info(
            "QP parsed",
            extra={
                "conversation_id": thread_id,
                "intent": qp_output["intent"],
                "intent_detail": qp_output["intent_detail"],
                "missing_required": qp_output["missing_required"],
            },
        )
        return {
            "qp_output": qp_output,
            "normalized_query": qp_output["normalized_query"],
            "recall_query": qp_output["recall_query"],
            "intent": qp_output["intent"],
            "intent_detail": qp_output["intent_detail"],
        }

    async def upsert_query_state(self, *, thread_id: str, user_id: int, query_text: str) -> None:
        await ConversationService.upsert_travel_conversation_state(
            conversation_id=thread_id,
            user_id=user_id,
            last_user_query=query_text,
        )

    async def handle_non_create_intent(
        self,
        *,
        thread_id: str,
        request_id: str,
        user_id: int,
        query_text: str,
        intent: str,
        intent_detail: str,
    ) -> StreamingResponse | None:
        if intent == "reset":
            self._clarification_service.clear_pending(thread_id)
            await ConversationService.reset_travel_conversation_state(
                conversation_id=thread_id,
                user_id=user_id,
                last_user_query=query_text,
            )
            return self.stream_response(
                self._stream_service.stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                    text=TRAVEL_API_RULES.text_reset_done,
                    event_name=TRAVEL_API_RULES.event_reset_done,
                ),
                conversation_id=thread_id,
            )

        if intent not in {"edit", "qa"}:
            return None

        state = await ConversationService.get_travel_conversation_state(thread_id)
        has_itinerary = bool(state and state.get("current_itinerary"))
        if not has_itinerary:
            return self.stream_response(
                self._stream_service.stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                    text=TRAVEL_API_RULES.text_need_itinerary_for_edit,
                ),
                conversation_id=thread_id,
            )

        if intent == "qa":
            return self.stream_response(
                self._stream_service.stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                    text=TRAVEL_API_RULES.text_qa_placeholder,
                ),
                conversation_id=thread_id,
            )

        patch_result = self._patch_engine.apply_edit_query(
            query=query_text,
            itinerary=state["current_itinerary"],
        )
        if not patch_result["ok"]:
            return self.stream_response(
                self._stream_service.stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                    text=patch_result["message"],
                ),
                conversation_id=thread_id,
            )

        updated_itinerary = patch_result["itinerary"]
        await ConversationService.upsert_travel_conversation_state(
            conversation_id=thread_id,
            user_id=user_id,
            current_revision_id=updated_itinerary.get("revision_id"),
            trip_profile=updated_itinerary.get("trip_profile"),
            current_itinerary=updated_itinerary,
            last_user_query=query_text,
        )
        return self.stream_response(
            self._stream_service.stream_intent_itinerary_response(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
                itinerary=updated_itinerary,
                explanation=patch_result["message"],
            ),
            conversation_id=thread_id,
        )

    async def build_query_create_response(
        self,
        *,
        request_id: str,
        thread_id: str,
        user_id: int,
        intent: str,
        intent_detail: str,
        normalized_query: str,
        recall_query: str,
        thread_config: dict,
    ) -> StreamingResponse:
        decision = self._clarification_service.start_new(thread_id=thread_id, query=normalized_query)
        if decision["need_clarification"]:
            self._logger.info(
                f"Clarification required for thread={thread_id}, "
                f"missing_hard={decision['missing_hard']}, missing_soft={decision['missing_soft']}"
            )

            async def process_clarification():
                async for line in self._stream_service.stream_intent_routed_event(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                ):
                    yield line
                async for line in self._stream_service.stream_clarification_events(
                    request_id=request_id,
                    conversation_id=thread_id,
                    missing_hard=decision["missing_hard"],
                    missing_soft=decision["missing_soft"],
                ):
                    yield line

            return self.stream_response(process_clarification(), conversation_id=thread_id)

        self._logger.info("Clarification gate passed, generating minimal itinerary draft.")

        async def process_stream():
            async for line in self._stream_service.stream_intent_routed_event(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
            ):
                yield line
            async for line in self._stream_service.stream_minimal_itinerary(
                query_text=recall_query,
                thread_config=thread_config,
                conversation_id=thread_id,
                request_id=request_id,
                user_id=user_id,
            ):
                yield line

        return self.stream_response(process_stream(), conversation_id=thread_id)

    async def build_resume_create_response(
        self,
        *,
        request_id: str,
        thread_id: str,
        user_id: int,
        intent: str,
        intent_detail: str,
        normalized_query: str,
        recall_query: str,
        thread_config: dict,
    ) -> StreamingResponse:
        if self._clarification_service.has_pending(thread_id):
            decision = self._clarification_service.continue_pending(thread_id=thread_id, query=normalized_query)
            if decision.get("need_clarification"):
                self._logger.info(
                    f"Clarification still required for thread={thread_id}, "
                    f"missing_hard={decision['missing_hard']}, missing_soft={decision['missing_soft']}"
                )

                async def process_clarification():
                    async for line in self._stream_service.stream_intent_routed_event(
                        request_id=request_id,
                        conversation_id=thread_id,
                        intent=intent,
                        intent_detail=intent_detail,
                    ):
                        yield line
                    async for line in self._stream_service.stream_clarification_events(
                        request_id=request_id,
                        conversation_id=thread_id,
                        missing_hard=decision["missing_hard"],
                        missing_soft=decision["missing_soft"],
                    ):
                        yield line

                return self.stream_response(process_clarification(), conversation_id=thread_id)

            combined_query = decision["combined_query"]
            combined_qp_output = self._query_processor.process(combined_query)
            combined_recall_query = combined_qp_output["recall_query"]
            self._logger.info(f"Clarification completed for thread={thread_id}, continuing planning flow.")

            async def process_resume_after_clarification():
                async for line in self._stream_service.stream_intent_routed_event(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                ):
                    yield line
                async for line in self._stream_service.stream_minimal_itinerary(
                    query_text=combined_recall_query,
                    thread_config=thread_config,
                    conversation_id=thread_id,
                    request_id=request_id,
                    user_id=user_id,
                ):
                    yield line

            return self.stream_response(
                process_resume_after_clarification(),
                conversation_id=thread_id,
            )

        async def process_resume():
            async for line in self._stream_service.stream_intent_routed_event(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
            ):
                yield line
            async for line in self._stream_service.stream_minimal_itinerary(
                query_text=recall_query,
                thread_config=thread_config,
                conversation_id=thread_id,
                request_id=request_id,
                user_id=user_id,
            ):
                yield line

        return self.stream_response(process_resume(), conversation_id=thread_id)

    @staticmethod
    def new_request_id() -> str:
        return new_uuid()
