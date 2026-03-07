from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.travel_handlers import TravelRequestHandler
from app.api.travel_streams import TravelStreamService
from app.core.logger import get_logger
from app.domain.travel.patch_engine import TravelPatchEngine
from app.domain.travel.query_processor import TravelQueryProcessor
from app.services.conversation_service import ConversationService
from app.services.travel_clarification_service import TravelClarificationService

router = APIRouter()
logger = get_logger(service="travel_api")
clarification_service = TravelClarificationService()
query_processor = TravelQueryProcessor()
patch_engine = TravelPatchEngine()
stream_service = TravelStreamService(
    clarification_service=clarification_service,
    logger=logger,
)
request_handler = TravelRequestHandler(
    query_processor=query_processor,
    patch_engine=patch_engine,
    clarification_service=clarification_service,
    stream_service=stream_service,
    logger=logger,
)


class LangGraphResumeRequest(BaseModel):
    """恢复会话请求体。"""

    query: str
    user_id: int
    conversation_id: str


@router.post("/travel/query")
@router.post("/langgraph/query")
async def langgraph_query(
    query: str = Form(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
):
    """旅行规划主入口：新建/续跑会话 + 澄清门槛 + SSE 流式输出。"""
    try:
        logger.info(f"Processing travel planning query for user {user_id} and conversation {conversation_id}")

        image_path = None
        if image:
            image_path, _, _ = await request_handler.save_uploaded_image(image=image)
            logger.info(f"Saved image {image_path.name} for user {user_id}")

        thread_id = conversation_id if conversation_id else request_handler.new_request_id()
        request_id = request_handler.new_request_id()
        qp_data = request_handler.parse_qp(query_text=query, thread_id=thread_id)
        intent = qp_data["intent"]
        intent_detail = qp_data["intent_detail"]
        normalized_query = qp_data["normalized_query"]
        recall_query = qp_data["recall_query"]

        await request_handler.upsert_query_state(
            thread_id=thread_id,
            user_id=user_id,
            query_text=query,
        )
        thread_config = request_handler.build_thread_config(
            thread_id=thread_id,
            user_id=user_id,
            image_path=image_path,
        )

        non_create_response = await request_handler.handle_non_create_intent(
            thread_id=thread_id,
            request_id=request_id,
            user_id=user_id,
            query_text=query,
            intent=intent,
            intent_detail=intent_detail,
        )
        if non_create_response is not None:
            return non_create_response

        return await request_handler.build_query_create_response(
            request_id=request_id,
            thread_id=thread_id,
            user_id=user_id,
            intent=intent,
            intent_detail=intent_detail,
            normalized_query=normalized_query,
            recall_query=recall_query,
            thread_config=thread_config,
        )
    except Exception as exc:
        logger.error(f"LangGraph query error: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/travel/resume")
@router.post("/langgraph/resume")
async def langgraph_resume(request: LangGraphResumeRequest):
    """恢复旅行规划流程：优先补全 pending 澄清，再 resume 图执行。"""
    try:
        logger.info(
            f"Resuming travel planning query for user {request.user_id} with conversation {request.conversation_id}"
        )

        thread_id = request.conversation_id
        request_id = request_handler.new_request_id()
        qp_data = request_handler.parse_qp(query_text=request.query, thread_id=thread_id)
        intent = qp_data["intent"]
        intent_detail = qp_data["intent_detail"]
        normalized_query = qp_data["normalized_query"]
        recall_query = qp_data["recall_query"]

        await request_handler.upsert_query_state(
            thread_id=thread_id,
            user_id=request.user_id,
            query_text=request.query,
        )
        thread_config = request_handler.build_thread_config(
            thread_id=thread_id,
            user_id=request.user_id,
        )

        non_create_response = await request_handler.handle_non_create_intent(
            thread_id=thread_id,
            request_id=request_id,
            user_id=request.user_id,
            query_text=request.query,
            intent=intent,
            intent_detail=intent_detail,
        )
        if non_create_response is not None:
            return non_create_response

        return await request_handler.build_resume_create_response(
            request_id=request_id,
            thread_id=thread_id,
            user_id=request.user_id,
            intent=intent,
            intent_detail=intent_detail,
            normalized_query=normalized_query,
            recall_query=recall_query,
            thread_config=thread_config,
        )
    except Exception as exc:
        logger.error(f"LangGraph resume error: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/travel/state/{conversation_id}")
async def get_travel_state(conversation_id: str):
    """读取会话当前行程状态（T-M2-010 验收辅助接口）。"""
    try:
        state = await ConversationService.get_travel_conversation_state(conversation_id)
        if not state:
            return {"conversation_id": conversation_id, "state": None}
        return {"conversation_id": conversation_id, "state": state}
    except Exception as exc:
        logger.error(f"Get travel state error: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/upload/image")
async def upload_image(
    image: UploadFile = File(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None),
):
    """独立图片上传接口：只做文件落盘并返回元数据。"""
    try:
        image_path, timestamp, content_size = await request_handler.save_uploaded_image(
            image=image,
            conversation_id=conversation_id,
        )
        image_info = {
            "filename": image_path.name,
            "original_name": image.filename,
            "size": content_size,
            "type": image.content_type,
            "path": str(image_path).replace("\\", "/"),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "upload_time": timestamp,
        }
        logger.info(f"Image uploaded: {image_info}")
        return image_info
    except Exception as exc:
        logger.error(f"Image upload failed for user {user_id}: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
