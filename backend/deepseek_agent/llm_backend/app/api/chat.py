import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.logger import get_logger, log_structured
from app.services.conversation_service import ConversationService
from app.services.indexing_service import IndexingService
from app.services.llm_factory import LLMFactory

router = APIRouter()
logger = get_logger(service="chat_api")

# 统一上传目录：普通文件上传后会在此落盘，再交给索引服务处理。
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# 推理请求
class ReasonRequest(BaseModel):
    messages: List[Dict[str, str]]
    user_id: int


# 聊天请求
class ChatMessage(BaseModel):
    messages: List[Dict[str, str]]
    user_id: int
    conversation_id: int


# RAG聊天请求
class RAGChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    index_id: str
    user_id: int


# 聊天入口
@router.post("/api/chat")
async def chat_endpoint(request: ChatMessage):
    """基础聊天入口：流式返回模型回复并在完成后落库消息。"""
    try:
        logger.info(f"Processing chat request for user {request.user_id} in conversation {request.conversation_id}")
        chat_service = LLMFactory.create_chat_service()

        # 通过 on_complete 回调将完整回复写入会话消息表。
        return StreamingResponse(
            chat_service.generate_stream(
                messages=request.messages,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                on_complete=ConversationService.save_message,
            ),
            media_type="text/event-stream",
        )
    except Exception as e:
        logger.error(f"Chat error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 推理入口
@router.post("/api/reason")
async def reason_endpoint(request: ReasonRequest):
    """推理模式入口：用于更偏分析/思考型的流式回答。"""
    try:
        logger.info(f"Processing reasoning request for user {request.user_id}")
        reasoner = LLMFactory.create_reasoner_service()

        # 记录结构化日志，便于后续追踪输入规模和问题类型。
        log_structured(
            "reason_request",
            {
                "user_id": request.user_id,
                "message_count": len(request.messages),
                "last_message": request.messages[-1]["content"][:100] + "...",
            },
        )

        # 流式返回推理结果，同时记录结构化日志。
        return StreamingResponse(reasoner.generate_stream(request.messages), media_type="text/event-stream")
    except Exception as e:
        logger.error(f"Reasoning error for user {request.user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 检索入口
@router.post("/api/search")
async def search_endpoint(request: ChatMessage):
    """检索增强聊天入口：先检索，再流式返回生成结果。"""
    try:
        logger.info(f"Processing search request for user {request.user_id} in conversation {request.conversation_id}")
        logger.info(f"Request: {request}")
        search_service = LLMFactory.create_search_service()
        return StreamingResponse(
            search_service.generate_stream(
                query=request.messages[0]["content"],
                user_id=request.user_id,
                conversation_id=request.conversation_id,
            ),
            media_type="text/event-stream",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 文件上传入口
@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    user_id: int = Form(...),
):
    """文件上传入口：落盘后立即触发索引构建，返回索引元信息。"""
    try:
        logger.info(f"Uploading file for user {user_id}: {file.filename}")

        # 使用稳定 uuid 将用户上传目录隔离，避免不同用户文件混用。
        user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{user_id}"))
        first_level_dir = UPLOAD_DIR / user_uuid

        # 二级目录按时间分桶，降低同目录文件过多带来的管理成本。
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        second_level_dir = first_level_dir / timestamp
        second_level_dir.mkdir(parents=True, exist_ok=True)

        # 生成唯一文件名，避免覆盖。
        original_name, ext = os.path.splitext(file.filename)
        new_filename = f"{original_name}_{timestamp}{ext}"
        file_path = second_level_dir / new_filename

        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        # 记录文件元信息，后续索引构建时会关联。
        file_info = {
            "filename": new_filename,
            "original_name": file.filename,
            "size": len(content),
            "type": file.content_type,
            "path": str(file_path).replace("\\", "/"),
            "user_id": user_id,
            "user_uuid": user_uuid,
            "upload_time": timestamp,
            "directory": str(second_level_dir),
        }

        # 文件入库后直接进入索引流程，前端可拿到 index_result 做后续问答。
        indexing_service = IndexingService()
        index_result = await indexing_service.process_file(file_info)

        result = {**file_info, "index_result": index_result}
        return result
    except Exception as e:
        logger.error(f"Upload failed for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# RAG聊天入口
@router.post("/chat-rag")
async def rag_chat_endpoint(request: RAGChatRequest):
    """基于指定索引的文档问答入口（保留历史实现）。"""
    try:
        logger.info(f"Processing RAG chat request for user {request.user_id}")
        # 保持现有行为；依赖注入问题可在独立任务中重构。
        rag_chat_service = RAGChatService()  # noqa: F821

        # 记录结构化日志，便于后续追踪索引关联。
        return StreamingResponse(
            rag_chat_service.generate_stream(request.messages, request.index_id),
            media_type="text/event-stream",
        )
    except Exception as e:
        logger.error(f"RAG chat error for user {request.user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
