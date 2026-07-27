"""
Rule definitions for travel clarification.

Keep detection patterns and field strategy outside service logic
to avoid hardcoding business rules in flow orchestration code.
"""

from typing import Dict, List, Tuple

# Field strategy
HARD_REQUIRED_FIELDS: Tuple[str, ...] = ("destination", "duration", "budget")
SOFT_RECOMMENDED_FIELDS: Tuple[str, ...] = ("travelers",)

FIELD_LABELS: Dict[str, str] = {
    "destination": "目的地城市",
    "duration": "出行天数/日期范围",
    "budget": "预算区间",
    "travelers": "出行人群",
}

GUIDED_FIELD_HINTS: Dict[str, str] = {
    "destination": "想去哪里旅行",
    "duration": "计划玩几天",
    "budget": "大概的预算范围",
    "travelers": "和谁一起出行",
}

# Clarification message templates
# NOTE:
# - Keep wording here so product copy can evolve without touching service logic.
# - Service should only fill placeholders, not hardcode Chinese copy.
CLARIFICATION_MSG_HARD_ONLY = "为保证行程可执行，请先补充：{hard_text}。"
CLARIFICATION_MSG_HARD_AND_SOFT = (
    "为保证行程可执行，请先补充：{hard_text}。"
    "另外建议补充：{soft_text}（可选，不填也能先出草案）。"
)

# SSE event/stage constants for clarification flow
SSE_EVENT_STAGE_START = "stage_start"
SSE_EVENT_STAGE_PROGRESS = "stage_progress"
CLARIFICATION_STAGE_NAME = "clarify_constraints"

# Pattern library (data-only; service is responsible for execution).
CONSTRAINT_PATTERNS: Dict[str, List[str]] = {
    "destination": [
        r"(去|到|前往|飞往|想去|目的地)\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z\s\-\.'/]{1,40})",
        # 支持“上海 4 天”“北京3天”这类直接城市+时长表达
        r"([\u4e00-\u9fa5A-Za-z]{2,20})\s*\d+\s*(天|日|晚|夜)",
        r"\b(to|in|visit|travel to|go to|destination)\s+([A-Za-z][A-Za-z\s\-]{1,40})\b",
        r"(城市|city|country|国家)\s*[:：]?\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5\s\-]{1,40})",
    ],
    "duration": [
        r"(\d+\s*[天日])|(\d+\s*(day|days|晚|夜))",
        r"[一二两三四五六七八九十]+\s*[天日周]",
        r"\d+\s*周",
        r"一周|两周|半个月",
    ],
    "budget": [
        r"(预算|人均|总价|费用|cost|budget)",
        r"(¥|￥|\$|€|£|\d+\s*(元|块钱?|千|k|K|万|w|W|usd|eur|gbp))",
        r"[一二两三四五六七八九十]+\s*(万|千|百)",
        r"\d{3,}\s*(左右|以内|以下|上下|出头)",
    ],
    "travelers": [
        r"(独行|独自|一个人|情侣|亲子|家庭|朋友|多人|solo|couple|family|friends|group)",
        r"\d+\s*人",
    ],
}

# A flexible answer may accept product defaults for duration and budget, but it
# can never supply a missing destination.
FLEXIBLE_ANSWER_PATTERNS: Tuple[str, ...] = (
    r"^(都可以|都行|随便|均可|你安排(?:就好)?|你决定(?:就好)?|都听你的)[。！!.\s]*$",
    r"^(anything is fine|either is fine|you decide|up to you)[.!?\s]*$",
)

DEFAULT_DURATION_DAYS = 3
DEFAULT_DAILY_BUDGET = 2000
MIN_DEFAULT_BUDGET = 3000
