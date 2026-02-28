from typing import Any, Dict, List
from app.core.database import AsyncSessionLocal, engine
from app.models.conversation import Conversation, DialogueType
from app.models.message import Message
from app.models.travel_conversation_state import TravelConversationState
from app.core.logger import get_logger
from sqlalchemy import select

logger = get_logger(service="conversation")

class ConversationService:
    @staticmethod
    async def _ensure_travel_state_table() -> None:
        """确保旅行会话状态表存在（本地开发容错）。"""
        async with engine.begin() as conn:
            await conn.run_sync(
                TravelConversationState.__table__.create,
                checkfirst=True,
            )

    @staticmethod
    def get_conversation_title(message: str, max_length: int = 20) -> str:
        """从消息中提取会话标题"""
        title = " ".join(message.split())
        if len(title) > max_length:
            title = title[:max_length] + "..."
        return title

    @staticmethod
    async def create_conversation(user_id: int) -> int:
        """创建新会话"""
        async with AsyncSessionLocal() as db:
            conversation = Conversation(
                user_id=user_id,
                title="新会话",
                dialogue_type=DialogueType.NORMAL
            )
            db.add(conversation)
            await db.commit()
            await db.refresh(conversation)
            
            logger.info(f"Created new conversation {conversation.id} for user {user_id}")
            return conversation.id

    @staticmethod
    async def get_travel_conversation_state(conversation_id: str) -> Dict[str, Any] | None:
        """读取旅行会话当前状态。"""
        await ConversationService._ensure_travel_state_table() # 确保旅行会话状态表存在
        # 查询旅行会话状态
        async with AsyncSessionLocal() as db:
            stmt = select(TravelConversationState).where(
                # 查询条件：会话ID等于传入的会话ID
                TravelConversationState.conversation_id == conversation_id
            )
            # 执行查询
            result = await db.execute(stmt)
            state = result.scalar_one_or_none() # 获取查询结果
            # 如果查询结果为空，则返回空
            if not state:
                return None
            # 如果查询结果不为空，则返回查询结果
            return {
                "conversation_id": state.conversation_id,
                "user_id": state.user_id,
                "current_revision_id": state.current_revision_id,
                "trip_profile": state.trip_profile_json,
                "current_itinerary": state.current_itinerary_json,
                "last_user_query": state.last_user_query,
                "created_at": state.created_at.isoformat() if state.created_at else None,
                "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            }

    # 创建或更新旅行会话状态
    @staticmethod
    async def upsert_travel_conversation_state(
        *,
        conversation_id: str,
        user_id: int | None = None,
        current_revision_id: str | None = None,
        trip_profile: Dict[str, Any] | None = None,
        current_itinerary: Dict[str, Any] | None = None,
        last_user_query: str | None = None,
    ) -> Dict[str, Any]:
        """创建或更新旅行会话状态。"""
        await ConversationService._ensure_travel_state_table()
        async with AsyncSessionLocal() as db:
            # 查询旅行会话状态
            stmt = select(TravelConversationState).where(
                TravelConversationState.conversation_id == conversation_id
            )
            result = await db.execute(stmt)
            state = result.scalar_one_or_none()

            if not state:
                # 如果查询结果为空，则创建新的旅行会话状态
                state = TravelConversationState(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    current_revision_id=current_revision_id,
                    trip_profile_json=trip_profile,
                    current_itinerary_json=current_itinerary,
                    last_user_query=last_user_query,
                )
                db.add(state) # 添加新的旅行会话状态
            else:
                # 如果查询结果不为空，则更新旅行会话状态
                if user_id is not None:
                    state.user_id = user_id
                if current_revision_id is not None:
                    state.current_revision_id = current_revision_id
                if trip_profile is not None:
                    state.trip_profile_json = trip_profile
                if current_itinerary is not None:
                    state.current_itinerary_json = current_itinerary
                if last_user_query is not None:
                    state.last_user_query = last_user_query
            # 提交事务
            await db.commit()
            await db.refresh(state)

            # 返回旅行会话状态
            return {
                "conversation_id": state.conversation_id,
                "user_id": state.user_id,
                "current_revision_id": state.current_revision_id,
                "trip_profile": state.trip_profile_json,
                "current_itinerary": state.current_itinerary_json,
                "last_user_query": state.last_user_query,
                "created_at": state.created_at.isoformat() if state.created_at else None,
                "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            }

    @staticmethod
    async def reset_travel_conversation_state(
        *,
        conversation_id: str,
        user_id: int | None = None,
        last_user_query: str | None = None,
    ) -> Dict[str, Any]:
        """重置旅行会话状态（保留会话行，不保留行程快照）。"""
        await ConversationService._ensure_travel_state_table()
        async with AsyncSessionLocal() as db:
            stmt = select(TravelConversationState).where(
                TravelConversationState.conversation_id == conversation_id
            )
            result = await db.execute(stmt)
            state = result.scalar_one_or_none()

            # 如果查询结果为空，则创建新的旅行会话状态
            if not state:
                state = TravelConversationState(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    current_revision_id=None,
                    trip_profile_json=None,
                    current_itinerary_json=None,
                    last_user_query=last_user_query,
                )
                db.add(state)
            else:
                # 如果查询结果不为空，则更新旅行会话状态
                if user_id is not None:
                    state.user_id = user_id
                state.current_revision_id = None
                state.trip_profile_json = None
                state.current_itinerary_json = None
                if last_user_query is not None:
                    state.last_user_query = last_user_query
            # 提交事务
            await db.commit()
            await db.refresh(state)
            # 返回旅行会话状态
            return {
                "conversation_id": state.conversation_id,
                "user_id": state.user_id,
                "current_revision_id": state.current_revision_id,
                "trip_profile": state.trip_profile_json,
                "current_itinerary": state.current_itinerary_json,
                "last_user_query": state.last_user_query,
                "created_at": state.created_at.isoformat() if state.created_at else None,
                "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            }

    @staticmethod
    async def save_message(
        user_id: int, 
        conversation_id: int, 
        messages: List[Dict], 
        response: str
    ):
        """保存对话消息"""
        try:
            async with AsyncSessionLocal() as db:
                # 查询会话
                stmt = select(Conversation).where(Conversation.id == conversation_id)
                result = await db.execute(stmt)
                conversation = result.scalar_one_or_none()
                
                if not conversation:
                    logger.error(f"Conversation {conversation_id} not found")
                    return
                    
                # 查询现有消息数量
                stmt = select(Message).where(Message.conversation_id == conversation_id)
                result = await db.execute(stmt)
                messages_count = len(result.all())
                
                # 获取用户的问题内容
                user_content = next((msg["content"] for msg in messages if msg["role"] == "user"), "")
                
                # 如果是第一条消息，更新会话标题
                if messages_count == 0:
                    title = ConversationService.get_conversation_title(user_content)
                    conversation.title = title
                
                # 保存用户消息
                user_message = Message(
                    conversation_id=conversation_id,
                    sender="user",
                    content=user_content
                )
                db.add(user_message)
                
                # 保存助手回复
                assistant_message = Message(
                    conversation_id=conversation_id,
                    sender="assistant",
                    content=response
                )
                db.add(assistant_message)
                
                # 提交事务
                await db.commit()
                
        except Exception as e:
            # 记录错误日志
            logger.error(f"Error saving conversation: {str(e)}", exc_info=True)
            logger.error(f"Error details - user_id: {user_id}, conversation_id: {conversation_id}")
            logger.error(f"Messages: {messages}")

    @staticmethod
    async def get_user_conversations(user_id: int) -> List[Dict]:
        """获取用户的所有会话"""
        try:
            async with AsyncSessionLocal() as db:
         
                # 查询用户的所有会话，排除标题为"新会话"的对话
                stmt = select(Conversation).where(
                    Conversation.user_id == user_id,
                    Conversation.title != "新会话"  # 添加这个条件
                ).order_by(Conversation.created_at.desc())
                
                result = await db.execute(stmt)
                conversations = result.scalars().all()
                
                # 返回会话列表
                return [
                    {
                        "id": conv.id,
                        "title": conv.title,
                        "created_at": conv.created_at.isoformat(),
                        "status": conv.status,
                        "dialogue_type": conv.dialogue_type.value
                    }
                    for conv in conversations
                ]
                
        except Exception as e:
            logger.error(f"Error getting conversations for user {user_id}: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def get_conversation_messages(conversation_id: int, user_id: int) -> List[Dict]:
        """获取会话的所有消息"""
        try:
            async with AsyncSessionLocal() as db:
                # 首先验证会话属于该用户 
                stmt = select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id
                )
                result = await db.execute(stmt)
                conversation = result.scalar_one_or_none()

                # 如果会话不存在，则抛出错误
                if not conversation:
                    raise ValueError(f"Conversation {conversation_id} not found or not owned by user {user_id}")
                
                # 查询会话的所有消息 并按创建时间排序
                stmt = select(Message).where(
                    Message.conversation_id == conversation_id
                ).order_by(Message.created_at)
                
                result = await db.execute(stmt)
                messages = result.scalars().all()
                
                # 返回消息列表
                return [
                    {
                        "id": msg.id,
                        "sender": msg.sender,
                        "content": msg.content,
                        "created_at": msg.created_at.isoformat(),
                        "message_type": msg.message_type
                    }
                    for msg in messages
                ]
                
        except Exception as e:
            # 记录错误日志
            logger.error(f"Error getting messages for conversation {conversation_id}: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def delete_conversation(conversation_id: int):
        """删除会话及其所有消息"""
        try:
            async with AsyncSessionLocal() as db:
                # 查询会话 如果会话不存在，则抛出错误
                stmt = select(Conversation).where(Conversation.id == conversation_id)
                result = await db.execute(stmt)
                conversation = result.scalar_one_or_none()
                
                if not conversation:
                    raise ValueError(f"Conversation {conversation_id} not found")
                
                # 删除会话(会自动级联删除相关消息) 并提交事务
                await db.delete(conversation)
                await db.commit()
                
                logger.info(f"已删除会话 {conversation_id} 及其所有消息")
        except Exception as e:
            # 记录错误日志
            logger.error(f"删除会话失败: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def update_conversation_name(conversation_id: int, name: str):
        """更新会话名称"""
        try:
            async with AsyncSessionLocal() as db:
                # 查询会话 
                stmt = select(Conversation).where(Conversation.id == conversation_id)
                result = await db.execute(stmt)
                conversation = result.scalar_one_or_none()
                
                if not conversation:
                    raise ValueError(f"Conversation {conversation_id} not found")
                
                # 更新名称
                conversation.title = name
                await db.commit()
                
                logger.info(f"已更新会话 {conversation_id} 的名称为 {name}")
        except Exception as e:
            logger.error(f"更新会话名称失败: {str(e)}", exc_info=True)
            raise 