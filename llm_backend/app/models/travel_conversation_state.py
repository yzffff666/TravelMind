from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func

from app.core.database import Base


class TravelConversationState(Base):
    __tablename__ = "travel_conversation_states"
    __table_args__ = {"comment": "旅行会话状态表：记录会话当前行程与版本"}

    conversation_id = Column(String(64), primary_key=True, comment="会话ID（thread_id）")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属用户")
    current_revision_id = Column(String(64), nullable=True, index=True, comment="当前版本ID")
    trip_profile_json = Column(JSON, nullable=True, comment="当前行程画像快照（目的地/约束）")
    current_itinerary_json = Column(JSON, nullable=True, comment="当前完整行程快照")
    last_user_query = Column(Text, nullable=True, comment="最近一次用户输入")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
