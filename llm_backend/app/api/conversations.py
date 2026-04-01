from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.logger import get_logger
from app.services.conversation_service import ConversationService

router = APIRouter()
logger = get_logger(service="conversations_api")

# 创建会话
class CreateConversationRequest(BaseModel):
    user_id: int


# 更新会话名称
class UpdateConversationNameRequest(BaseModel):
    name: str


# 创建会话
@router.post("/conversations")
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    try:
        conversation_id = await ConversationService.create_conversation(request.user_id)
        return {"conversation_id": conversation_id}
    except Exception as e:
        logger.error(f"Error creating conversation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 获取用户会话
@router.get("/conversations/user/{user_id}")
async def get_user_conversations(user_id: int):
    """Get all conversations for a user."""
    try:
        conversations = await ConversationService.get_user_conversations(user_id)
        return conversations
    except Exception as e:
        logger.error(f"Error getting conversations: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 获取会话消息
@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: int, user_id: int):
    """Get all messages in a conversation."""
    try:
        messages = await ConversationService.get_conversation_messages(conversation_id, user_id)
        return messages
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting messages: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 删除会话
@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    """Delete a conversation and all its messages."""
    try:
        conversation_service = ConversationService()
        await conversation_service.delete_conversation(conversation_id)
        return {"message": "会话已删除"}
    except Exception as e:
        logger.error(f"删除会话失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 更新会话名称
@router.put("/conversations/{conversation_id}/name")
async def update_conversation_name(
    conversation_id: int,
    request: UpdateConversationNameRequest,
):
    """Update a conversation name."""
    try:
        conversation_service = ConversationService()
        await conversation_service.update_conversation_name(conversation_id, request.name)
        return {"message": "会话名称已更新"}
    except Exception as e:
        logger.error(f"更新会话名称失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
