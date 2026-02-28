from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QPRules:
    """Rule/config bundle for query processing baseline."""

    preference_keywords: tuple[str, ...]
    pace_keywords: dict[str, str]
    edit_hints: tuple[str, ...]
    reset_hints: tuple[str, ...]
    evidence_qa_hints: tuple[str, ...]
    edit_day_pattern: re.Pattern[str]
    qa_question_pattern: re.Pattern[str]
    recall_joiner: str = " | "


QP_RULES = QPRules(
    preference_keywords=(
        "文化",
        "美食",
        "自然",
        "海边",
        "亲子",
        "博物馆",
        "夜景",
        "购物",
        "徒步",
        "摄影",
    ),
    pace_keywords={
        "轻松": "relaxed",
        "慢节奏": "relaxed",
        "紧凑": "intensive",
        "特种兵": "intensive",
    },
    edit_hints=("修改", "改", "调整", "换成", "替换", "删掉", "增加"),
    reset_hints=("重置", "重新开始", "清空", "从头开始"),
    evidence_qa_hints=("为什么", "证据", "来源", "链接", "依据", "ref"),
    edit_day_pattern=re.compile(r"(第?\s*\d+\s*天|day\s*\d+)", re.IGNORECASE),
    qa_question_pattern=re.compile(r"[?？]|(几点|多久|开放|门票|交通|地址)"),
)
