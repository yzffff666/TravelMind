import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.logger import get_logger
from app.domain.travel.sse_envelope import (
    build_data_line,
    build_event_envelope,
    build_event_line,
)
from app.domain.travel.query_processor import TravelQueryProcessor
from app.lg_agent.travel_draft_graph import travel_draft_graph
from app.lg_agent.utils import new_uuid
from app.services.conversation_service import ConversationService
from app.services.travel_clarification_service import TravelClarificationService

router = APIRouter()
logger = get_logger(service="travel_api")
# 澄清服务实例：用于在进入主规划链路前做“硬门槛缺失即追问”拦截。
clarification_service = TravelClarificationService()
# QP baseline：统一上游 query 与下游输入语义（T-M2-000a）。
query_processor = TravelQueryProcessor()

# 构建SSE行
def _build_sse_line(payload: object) -> str:
    return build_data_line(payload)

# 流式意图路由事件
async def _stream_intent_routed_event(
    *,
    request_id: str,
    conversation_id: str,
    intent: str,
    intent_detail: str,
):
    # 构建事件行
    yield build_event_line(
        "intent_routed",
        # 构建事件包裹
        build_event_envelope(
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=None,
            payload={
                "intent": intent,
                "intent_detail": intent_detail,
            },
        ),
    )

# 流式意图文本响应
async def _stream_intent_text_response(
    *,
    request_id: str,
    conversation_id: str,
    intent: str,
    intent_detail: str,
    text: str,
    event_name: str = "final_text",
):
    # 流式意图路由事件
    async for line in _stream_intent_routed_event(
        request_id=request_id,
        conversation_id=conversation_id,
        intent=intent,
        intent_detail=intent_detail,
    ):
        yield line
    # 构建事件行
    yield build_event_line(
        # 构建事件包裹
        event_name,
        build_event_envelope(
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=None,
            payload={"text": text},
        ),
    )
    yield _build_sse_line(text)


# 流式澄清事件
async def _stream_clarification_events(
    *,
    request_id: str,
    conversation_id: str,
    missing_hard: list[str],
    missing_soft: list[str],
):
    # 构建澄清负载
    clarification_payload = clarification_service.build_clarification_payload(
        missing_hard=missing_hard,
        missing_soft=missing_soft,
    )
    # 阶段
    stage = clarification_payload["stage"]
    # 消息
    message = clarification_payload["message"]

    # 构建事件行
    yield build_event_line(
        "stage_start",
        build_event_envelope(
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=None,
            payload={"stage": stage},
        ),
    )
    # 构建事件行
    yield build_event_line(
        "stage_progress",
        build_event_envelope(
            request_id=request_id,
            conversation_id=conversation_id,
            revision_id=None,
            payload=clarification_payload,
        ),
    )
    # Text fallback for old clients.
    # 构建SSE行
    yield _build_sse_line(message)


# 流式最小行程草案
async def _stream_minimal_itinerary(
    *,
    query_text: str,
    thread_config: dict,
    conversation_id: str,
    request_id: str,
    user_id: int | None = None,
):
    try:
        # 调用行程草案生成图
        result = await travel_draft_graph.ainvoke(
            input={"query": query_text},
            config=thread_config,
        )
        # 最终行程草案
        final_itinerary = result.get("final_itinerary")
        # 解释
        explanation = result.get("explanation")
        # 最终文本
        final_text = result.get("final_text")

        # 如果最终行程草案为空
        if not final_itinerary:
            # 回退文本
            fallback_text = final_text or "未能生成结构化草案，请补充目的地、天数和预算后重试。"
            # 构建事件行
            yield build_event_line(
                "final_text",
                build_event_envelope(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    revision_id=None,
                    payload={"text": fallback_text},
                ),
            )
            # 构建SSE行
            yield _build_sse_line(fallback_text)
            return

        # 构建事件行
        yield build_event_line(
            "final_itinerary",
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
        # 持久化会话当前行程状态（T-M2-010）。
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
            # 状态写入失败不阻断 SSE 主链路。
            logger.error(
                f"Persist travel conversation state failed: {str(persist_error)}",
                exc_info=True,
            )
        # 兼容旧前端纯文本消费。
        if explanation:
            yield _build_sse_line(explanation)
    except Exception as e:
        logger.error(f"Generate travel draft failed: {str(e)}", exc_info=True)
        fallback_text = "草案生成失败，请稍后再试。"
        # 构建事件行
        yield build_event_line(
            "error",
            build_event_envelope(
                request_id=request_id,
                conversation_id=conversation_id,
                revision_id=None,
                payload={"text": fallback_text},
            ),
        )
        # 构建SSE行
        yield _build_sse_line(fallback_text)


# 创建行程恢复请求模型
class LangGraphResumeRequest(BaseModel):
    """恢复会话请求体。"""
    query: str
    user_id: int
    conversation_id: str

# 双路由别名：`/travel/*` 是新语义入口，`/langgraph/*` 兼容旧前端调用。
@router.post("/travel/query")
@router.post("/langgraph/query")
async def langgraph_query(
    query: str = Form(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
):
    """旅行规划主入口：新建/续跑会话 + 澄清门槛 + SSE 流式输出。"""
    # 处理行程查询请求
    try:
        logger.info(f"Processing travel planning query for user {user_id} and conversation {conversation_id}")

        # 图片是可选输入：用于多模态增强（如景点/酒店截图），不是行程生成必填项。
        image_path = None
        if image:
            image_dir = Path("uploads/images")
            image_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_name, ext = os.path.splitext(image.filename)
            new_filename = f"{original_name}_{timestamp}{ext}"
            image_path = image_dir / new_filename

            content = await image.read()
            with open(image_path, "wb") as f:
                f.write(content)

            logger.info(f"Saved image {new_filename} for user {user_id}")

        # 会话线程ID：有 conversation_id 就复用，否则生成新会话。
        thread_id = conversation_id if conversation_id else new_uuid()
        request_id = new_uuid()
        qp_output = query_processor.process(query)
        normalized_query = qp_output["normalized_query"]
        recall_query = qp_output["recall_query"]
        logger.info(
            "QP parsed",
            extra={
                "conversation_id": thread_id,
                "intent": qp_output["intent"],
                "intent_detail": qp_output["intent_detail"],
                "missing_required": qp_output["missing_required"],
            },
        )
        intent = qp_output["intent"]
        intent_detail = qp_output["intent_detail"]

        await ConversationService.upsert_travel_conversation_state(
            conversation_id=thread_id,
            user_id=user_id,
            last_user_query=query,
        )
        # 配置会透传到 LangGraph 节点（例如 image_path 可触发图片分析分支）。
        thread_config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
                "image_path": str(image_path) if image_path else None,
            }
        }

        if intent == "reset":
            clarification_service.clear_pending(thread_id)
            await ConversationService.reset_travel_conversation_state(
                conversation_id=thread_id,
                user_id=user_id,
                last_user_query=query,
            )
            response = StreamingResponse(
                _stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                    text="已为当前会话重置行程状态，你可以重新输入新的出行需求。",
                    event_name="reset_done",
                ),
                media_type="text/event-stream",
            )
            response.headers["X-Conversation-ID"] = thread_id
            return response

        if intent in {"edit", "qa"}:
            state = await ConversationService.get_travel_conversation_state(thread_id)
            has_itinerary = bool(state and state.get("current_itinerary"))
            if not has_itinerary:
                text = "当前会话还没有可编辑的行程，请先描述目的地、天数和预算生成草案。"
            elif intent == "edit":
                text = "已识别编辑意图，下一步将接入 patch 编辑引擎（T-M2-012）执行结构化修改。"
            else:
                text = "已识别问答意图，下一步将接入行程问答分支（T-M2-011 后续增强）。"
            response = StreamingResponse(
                _stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                    text=text,
                ),
                media_type="text/event-stream",
            )
            response.headers["X-Conversation-ID"] = thread_id
            return response

        # 每次 travel query 都先经过澄清门槛：硬门槛缺失则追问，补齐后再生成结构化草案。
        decision = clarification_service.start_new(thread_id=thread_id, query=normalized_query)
        if decision["need_clarification"]:
            logger.info(
                f"Clarification required for thread={thread_id}, "
                f"missing_hard={decision['missing_hard']}, missing_soft={decision['missing_soft']}"
            )
            async def process_clarification():
                async for line in _stream_intent_routed_event(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                ):
                    yield line
                async for line in _stream_clarification_events(
                    request_id=request_id,
                    conversation_id=thread_id,
                    missing_hard=decision["missing_hard"],
                    missing_soft=decision["missing_soft"],
                ):
                    yield line
            response = StreamingResponse(
                process_clarification(),
                media_type="text/event-stream",
            )
            response.headers["X-Conversation-ID"] = thread_id
            return response

        logger.info("Clarification gate passed, generating minimal itinerary draft.")

        async def process_stream():
            async for line in _stream_intent_routed_event(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
            ):
                yield line
            async for line in _stream_minimal_itinerary(
                query_text=recall_query,
                thread_config=thread_config,
                conversation_id=thread_id,
                request_id=request_id,
                user_id=user_id,
            ):
                yield line

        # 统一 SSE 输出，前端通过 `data:` 增量消费。
        response = StreamingResponse(process_stream(), media_type="text/event-stream")
        response.headers["X-Conversation-ID"] = thread_id
        return response
    except Exception as e:
        logger.error(f"LangGraph query error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 创建行程恢复路由
@router.post("/travel/resume")
@router.post("/langgraph/resume")
async def langgraph_resume(request: LangGraphResumeRequest):
    """恢复旅行规划流程：优先补全 pending 澄清，再 resume 图执行。"""
    # 处理行程恢复请求
    try:
        logger.info(f"Resuming travel planning query for user {request.user_id} with conversation {request.conversation_id}")

        # 创建线程ID
        thread_id = request.conversation_id
        request_id = new_uuid()
        qp_output = query_processor.process(request.query)
        normalized_query = qp_output["normalized_query"]
        recall_query = qp_output["recall_query"]
        logger.info(
            "QP parsed",
            extra={
                "conversation_id": thread_id,
                "intent": qp_output["intent"],
                "intent_detail": qp_output["intent_detail"],
                "missing_required": qp_output["missing_required"],
            },
        )
        intent = qp_output["intent"]
        intent_detail = qp_output["intent_detail"]

        await ConversationService.upsert_travel_conversation_state(
            conversation_id=thread_id,
            user_id=request.user_id,
            last_user_query=request.query,
        )
        thread_config = {"configurable": {"thread_id": thread_id, "user_id": request.user_id}}

        if intent == "reset":
            clarification_service.clear_pending(thread_id)
            await ConversationService.reset_travel_conversation_state(
                conversation_id=thread_id,
                user_id=request.user_id,
                last_user_query=request.query,
            )
            response = StreamingResponse(
                _stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                    text="已为当前会话重置行程状态，你可以重新输入新的出行需求。",
                    event_name="reset_done",
                ),
                media_type="text/event-stream",
            )
            response.headers["X-Conversation-ID"] = thread_id
            return response

        if intent in {"edit", "qa"}:
            state = await ConversationService.get_travel_conversation_state(thread_id)
            has_itinerary = bool(state and state.get("current_itinerary"))
            if not has_itinerary:
                text = "当前会话还没有可编辑的行程，请先描述目的地、天数和预算生成草案。"
            elif intent == "edit":
                text = "已识别编辑意图，下一步将接入 patch 编辑引擎（T-M2-012）执行结构化修改。"
            else:
                text = "已识别问答意图，下一步将接入行程问答分支（T-M2-011 后续增强）。"
            response = StreamingResponse(
                _stream_intent_text_response(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                    text=text,
                ),
                media_type="text/event-stream",
            )
            response.headers["X-Conversation-ID"] = thread_id
            return response

        # 若该线程仍有待澄清项，优先完成澄清闭环。
        if clarification_service.has_pending(thread_id):
            decision = clarification_service.continue_pending(thread_id=thread_id, query=normalized_query)
            if decision.get("need_clarification"):
                # 创建澄清响应
                logger.info(
                    f"Clarification still required for thread={thread_id}, "
                    f"missing_hard={decision['missing_hard']}, missing_soft={decision['missing_soft']}"
                )
                # 创建流响应
                async def process_clarification():
                    async for line in _stream_intent_routed_event(
                        request_id=request_id,
                        conversation_id=thread_id,
                        intent=intent,
                        intent_detail=intent_detail,
                    ):
                        yield line
                    async for line in _stream_clarification_events(
                        request_id=request_id,
                        conversation_id=thread_id,
                        missing_hard=decision["missing_hard"],
                        missing_soft=decision["missing_soft"],
                    ):
                        yield line
                response = StreamingResponse(
                    process_clarification(),
                    media_type="text/event-stream",
                )
                response.headers["X-Conversation-ID"] = thread_id
                return response

            # 将初始 query 与补充信息合并后重启输入，避免上下文丢失。
            combined_query = decision["combined_query"]
            combined_qp_output = query_processor.process(combined_query)
            combined_recall_query = combined_qp_output["recall_query"]
            logger.info(f"Clarification completed for thread={thread_id}, continuing planning flow.")

            # 创建流响应
            async def process_resume_after_clarification():
                async for line in _stream_intent_routed_event(
                    request_id=request_id,
                    conversation_id=thread_id,
                    intent=intent,
                    intent_detail=intent_detail,
                ):
                    yield line
                async for line in _stream_minimal_itinerary(
                    query_text=combined_recall_query,
                    thread_config=thread_config,
                    conversation_id=thread_id,
                    request_id=request_id,
                    user_id=request.user_id,
                ):
                    yield line

            response = StreamingResponse(process_resume_after_clarification(), media_type="text/event-stream")
            response.headers["X-Conversation-ID"] = thread_id
            return response

        # 无 pending 时，直接按当前补充信息生成最小结构化草案。
        async def process_resume():
            async for line in _stream_intent_routed_event(
                request_id=request_id,
                conversation_id=thread_id,
                intent=intent,
                intent_detail=intent_detail,
            ):
                yield line
            async for line in _stream_minimal_itinerary(
                query_text=recall_query,
                thread_config=thread_config,
                conversation_id=thread_id,
                request_id=request_id,
                user_id=request.user_id,
            ):
                yield line

        response = StreamingResponse(process_resume(), media_type="text/event-stream")
        response.headers["X-Conversation-ID"] = thread_id
        return response

    except Exception as e:
        logger.error(f"LangGraph resume error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/travel/state/{conversation_id}")
async def get_travel_state(conversation_id: str):
    """读取会话当前行程状态（T-M2-010 验收辅助接口）。"""
    try:
        state = await ConversationService.get_travel_conversation_state(conversation_id)
        if not state:
            return {"conversation_id": conversation_id, "state": None}
        return {"conversation_id": conversation_id, "state": state}
    except Exception as e:
        logger.error(f"Get travel state error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 创建图片上传路由
@router.post("/upload/image")
async def upload_image(
    image: UploadFile = File(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None),
):
    """独立图片上传接口：只做文件落盘并返回元数据。"""
    # 处理图片上传请求
    try:
        # 按会话隔离目录，便于后续会话级清理与追踪。
        image_dir = Path("uploads/images")
        # 如果存在会话ID，则使用会话ID作为图片目录
        if conversation_id:
            image_dir = image_dir / conversation_id
        image_dir.mkdir(parents=True, exist_ok=True)

        # 创建时间戳
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 创建图片文件名
        original_name, ext = os.path.splitext(image.filename)
        new_filename = f"{original_name}_{timestamp}{ext}"
        # 创建图片路径
        image_path = image_dir / new_filename
        # 读取图片内容

        content = await image.read()
        # 写入图片内容
        with open(image_path, "wb") as f:
            f.write(content)

        # 创建图片信息
        image_info = {
            "filename": new_filename,
            "original_name": image.filename,
            "size": len(content),
            "type": image.content_type,
            "path": str(image_path).replace("\\", "/"),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "upload_time": timestamp,
        }

        # 记录图片上传日志
        logger.info(f"Image uploaded: {image_info}")
        # 返回图片信息
        return image_info
    except Exception as e:
        # 记录图片上传失败日志
        logger.error(f"Image upload failed for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
