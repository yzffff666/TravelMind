"""
T-M2-012 Patch 编辑引擎规则与文案配置。
- 关键词、正则、时段别名、影响范围阈值、用户可见文案均在此维护，避免在 patch_engine 中硬编码。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class PatchRules:
    """Patch 解析与文案配置，与 qp_rules / clarification_rules 同风格。"""

    # 意图识别关键词
    replace_hints: Tuple[str, ...]
    delete_hints: Tuple[str, ...]
    insert_hints: Tuple[str, ...]

    # 正则：天数、预算、新活动内容
    day_pattern: re.Pattern[str]
    budget_pattern: re.Pattern[str]
    activity_patterns: Tuple[re.Pattern[str], ...]

    # 时段别名 -> 规范名（用于匹配与插入）
    slot_aliases: Tuple[Tuple[str, str], ...]

    # 影响范围阈值：ratio <= local_threshold -> local, <= adjacent_threshold -> adjacent, else broad
    local_threshold: float
    adjacent_threshold: float

    # 默认插入时段名（当未识别到具体时段时）
    default_slot_label: str

    # 预算展示模板（trip_profile.constraints.budget_range）
    budget_range_template: str

    # 用户可见文案（便于产品/多语言后续调整）
    msg_invalid_itinerary: str
    msg_no_operation: str
    msg_budget_no_value: str
    msg_need_day: str
    msg_day_not_found: str
    msg_delete_need_slot: str
    msg_delete_min_slots: str
    msg_replace_need_slot: str
    msg_replace_need_activity: str
    msg_insert_need_activity: str
    msg_validate_failed: str
    msg_edit_done_local: str
    msg_edit_done: str
    msg_diff_join: str
    # 变更项文案模板（diff_items）
    diff_budget_updated: str
    diff_slot_deleted: str
    diff_slot_replaced: str
    diff_slot_inserted: str


PATCH_RULES = PatchRules(
    replace_hints=("替换", "换成", "改成", "改为", "replace"),
    delete_hints=("删除", "删掉", "去掉", "remove", "delete"),
    insert_hints=("新增", "添加", "加上", "安排", "insert", "add"),
    day_pattern=re.compile(r"(?:第?\s*(\d+)\s*天|day\s*(\d+))", re.IGNORECASE),
    budget_pattern=re.compile(
        r"(?:预算|budget)\s*(?:改成|改为|调整为|to)?\s*([0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    ),
    activity_patterns=(
        re.compile(r"(?:换成|改成|改为|替换为|替换成)\s*([^\n，。,；;]+)"),
        re.compile(r"(?:新增|添加|加上|安排)\s*([^\n，。,；;]+)"),
        re.compile(r"(?:to|with)\s+([A-Za-z][^,.;\n]+)", re.IGNORECASE),
    ),
    slot_aliases=(
        ("morning", "上午"),
        ("上午", "上午"),
        ("早上", "上午"),
        ("afternoon", "下午"),
        ("下午", "下午"),
        ("noon", "下午"),
        ("evening", "晚上"),
        ("night", "晚上"),
        ("晚上", "晚上"),
        ("夜晚", "晚上"),
    ),
    local_threshold=0.2,
    adjacent_threshold=0.5,
    default_slot_label="补充",
    budget_range_template="约{budget}元",
    msg_invalid_itinerary="当前行程数据无效，无法编辑：{detail}",
    msg_no_operation="未识别到可执行的编辑操作。请明确说明第几天、哪个时段，以及要改成什么。",
    msg_budget_no_value="已识别预算修改，但未识别到有效预算数值。",
    msg_need_day="请指定要修改的天数（例如：第2天）。",
    msg_day_not_found="未找到第{day_index}天，请检查天数范围。",
    msg_delete_need_slot="删除操作需要指定时段（上午/下午/晚上）。",
    msg_delete_min_slots="该天只剩 1 个时段，删除会导致行程无效。",
    msg_replace_need_slot="替换操作需要指定时段（上午/下午/晚上）。",
    msg_replace_need_activity="替换操作需要提供新的活动内容。",
    msg_insert_need_activity="新增操作需要提供活动内容。",
    msg_validate_failed="编辑后校验失败：{detail}",
    msg_edit_done_local="已完成局部编辑（影响范围：{impact_level}）。",
    msg_edit_done="已完成编辑（影响范围：{impact_level}）。",
    msg_diff_join="；",
    diff_budget_updated="预算更新为 {budget} 元",
    diff_slot_deleted="第{day_index}天{slot}已删除",
    diff_slot_replaced="第{day_index}天{slot}：{old_activity} -> {new_activity}",
    diff_slot_inserted="第{day_index}天新增时段：{slot} -> {activity}",
)
