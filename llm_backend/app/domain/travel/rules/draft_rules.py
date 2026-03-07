import re
from dataclasses import dataclass
from typing import Final

# 行程草案配置
@dataclass(frozen=True)
class DraftConfig:
    # 天数模式
    days_pattern: re.Pattern[str]
    # 预算模式
    budget_pattern: re.Pattern[str]
    # 目的地模式
    destination_patterns: tuple[re.Pattern[str], ...]
    # 出行人群关键词
    traveler_keywords: tuple[str, ...]
    # 天数模板
    day_slot_templates: tuple[tuple[str, str], ...]
    # 必填标签
    required_labels: tuple[str, ...]
    # 最大天数
    max_days: int = 14
    # 最小天数
    min_days: int = 1
    # 预算提示模板
    budget_hint_template: str = "约{budget}元"
    # 缺失P0模板
    missing_p0_template: str = "为了生成结构化行程草案，请补充：{missing_fields}。"
    # 出行人群默认假设
    traveler_default_assumption: str = "未提供出行人群，默认按通用休闲偏好生成草案。"
    # 解释模板
    explanation_template: str = "已基于你提供的约束生成 {days} 天的最小行程草案。"

# 行程草案配置实例
DRAFT_CONFIG: Final[DraftConfig] = DraftConfig(
    # 天数模式
    days_pattern=re.compile(r"(\d+)\s*天"),
    # 预算模式
    budget_pattern=re.compile(r"预算\s*([0-9]+(?:\.[0-9]+)?)"),
    # 目的地模式
    destination_patterns=(
        re.compile(r"(?:去|到|在)\s*([A-Za-z\u4e00-\u9fa5]{2,20})"),
        re.compile(r"([A-Za-z\u4e00-\u9fa5]{2,20})\s*\d+\s*天"),
    ),
    # 出行人群关键词
    traveler_keywords=("亲子", "情侣", "家庭", "独自", "朋友"),
    # 天数模板
    day_slot_templates=(
        ("上午", "第{day}天城市漫步与地标打卡"),
        ("下午", "第{day}天核心景点参观"),
        ("晚上", "第{day}天美食与休闲活动"),
    ),
    required_labels=("目的地", "行程天数", "预算"),
)
