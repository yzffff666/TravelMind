from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class ItineraryRevision(Base):
    __tablename__ = "itinerary_revisions"
    __table_args__ = {"comment": "行程版本表：每次生成/编辑产生一条版本记录"}

    id = Column(Integer, primary_key=True, index=True, comment="数据库自增主键（内部关联用）")
    itinerary_id = Column(Integer, ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属行程（删除行程时级联删除版本）")
    revision_id = Column(String(64), unique=True, nullable=False, index=True, comment="版本业务ID（对外可见，唯一）")
    base_revision_id = Column(String(64), nullable=True, index=True, comment="基线版本ID（从哪个版本演化而来；首版可为空）")
    request_id = Column(String(64), nullable=True, index=True, comment="请求幂等ID（用于防重复提交，后续任务使用）")
    payload_json = Column(JSON, nullable=False, comment="当次版本完整结构化快照")
    change_summary_json = Column(JSON, nullable=True, comment="当次变更摘要快照（便于展示与审计）")
    created_at = Column(DateTime, server_default=func.now(), comment="版本创建时间")

    # 关联：该版本所属的行程。
    itinerary = relationship("Itinerary", back_populates="revisions")
