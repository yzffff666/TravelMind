from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class ItineraryEvidence(Base):
    __tablename__ = "itinerary_evidence"
    __table_args__ = {"comment": "行程证据表：保存用于推荐解释的只读证据元数据"}

    id = Column(Integer, primary_key=True, index=True, comment="数据库自增主键（内部关联用）")
    itinerary_id = Column(Integer, ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属行程（删除行程时级联删除证据）")
    revision_id = Column(Integer, ForeignKey("itinerary_revisions.id", ondelete="CASCADE"), nullable=False, index=True, comment="关联版本（删除版本时级联删除证据）")
    evidence_id = Column(String(64), nullable=False, index=True, comment="证据业务ID（用于去重/追踪）")
    provider = Column(String(64), nullable=True, comment="数据来源标识（provider 抽象层名称）")
    title = Column(String(255), nullable=True, comment="证据标题（展示给用户）")
    url = Column(String(2048), nullable=True, comment="原始链接（支持跳转溯源）")
    snippet = Column(Text, nullable=True, comment="摘要片段（说明推荐依据）")
    fetched_at = Column(DateTime, nullable=True, comment="抓取时间（用于新鲜度提示）")
    attribution = Column(Text, nullable=True, comment="归因信息（版权/来源声明）")
    created_at = Column(DateTime, server_default=func.now(), comment="入库时间")

    # 关联：该证据所属的行程。
    itinerary = relationship("Itinerary", back_populates="evidence_items")
