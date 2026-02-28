from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base

class Itinerary(Base):
    __tablename__ = "itineraries"
    __table_args__ = {"comment": "主行程表：一条记录代表一份行程实体"}

    id = Column(Integer, primary_key=True, index=True, comment="数据库自增主键（内部关联用）")
    itinerary_id = Column(String(64), unique=True, nullable=False, index=True, comment="对外业务ID（接口/前端使用，保持稳定）")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="归属用户；用户删除后置空，保留行程历史")
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, comment="来源会话；会话删除后置空，保留行程历史")
    current_revision_id = Column(String(64), nullable=True, comment="当前最新版本ID（快速定位当前 revision）")
    schema_version = Column(String(32), nullable=False, default="itinerary.v1", comment="行程契约版本（与 itinerary schema 对齐）")
    trip_profile_json = Column(JSON, nullable=True, comment="行程画像快照（目的地/约束等顶层信息）")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间（DB 自动更新）")

    # 关联：该行程下的全部版本记录。
    revisions = relationship("ItineraryRevision", back_populates="itinerary", cascade="all, delete-orphan")
    # 关联：该行程下的差异记录。
    diffs = relationship("ItineraryDiff", back_populates="itinerary", cascade="all, delete-orphan")
    # 关联：该行程下的证据记录。
    evidence_items = relationship("ItineraryEvidence", back_populates="itinerary", cascade="all, delete-orphan")
