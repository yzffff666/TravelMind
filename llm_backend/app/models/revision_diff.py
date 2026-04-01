from sqlalchemy import Column, Integer, DateTime, ForeignKey, func, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class ItineraryDiff(Base):
    __tablename__ = "itinerary_diffs"
    __table_args__ = {"comment": "行程差异表：记录某个版本相对基线的变化结果"}

    id = Column(Integer, primary_key=True, index=True, comment="数据库自增主键（内部关联用）")
    itinerary_id = Column(Integer, ForeignKey("itineraries.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属行程（删除行程时级联删除差异）")
    revision_id = Column(Integer, ForeignKey("itinerary_revisions.id", ondelete="CASCADE"), nullable=False, index=True, comment="对应版本（删除版本时级联删除差异）")
    changed_days_json = Column(JSON, nullable=True, comment="受影响天列表（例如 [2,3]，用于前端高亮）")
    diff_items_json = Column(JSON, nullable=True, comment="细粒度差异项（字段级增删改摘要）")
    created_at = Column(DateTime, server_default=func.now(), comment="差异记录创建时间")

    # 关联：该差异所属的行程。
    itinerary = relationship("Itinerary", back_populates="diffs")
