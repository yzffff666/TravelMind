"""
T-M2-012 Patch 编辑引擎
将自然语言编辑指令解析为结构化操作，并 apply 到当前 itinerary 上，
产出新 revision + change_summary。
"""
from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from app.core.logger import get_logger

logger = get_logger(service="patch_engine")

# 编辑操作类型
class PatchOpType(str, Enum):
    # 替换 slot
    REPLACE_SLOT = "replace_slot"
    # 删除 slot
    DELETE_SLOT = "delete_slot"
    # 插入 slot
    INSERT_SLOT = "insert_slot"
    # 更新约束
    UPDATE_CONSTRAINT = "update_constraint"

# 编辑操作
@dataclass
class PatchOp:
    op: PatchOpType
    day_index: int | None = None
    slot_label: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class PatchResult:
    success: bool
    new_itinerary: dict[str, Any] | None = None
    old_revision_id: str | None = None
    new_revision_id: str | None = None
    change_summary: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    error: str | None = None


_DAY_PATTERN = re.compile(r"第\s*(\d+)\s*天")
_SLOT_LABELS = ("上午", "下午", "晚上")
_DELETE_HINTS = ("删掉", "删除", "去掉", "不要", "取消")
_ADD_HINTS = ("增加", "加上", "添加", "插入", "新增")
_REPLACE_HINTS = ("换成", "替换", "改成", "改为", "变成")
_BUDGET_PATTERN = re.compile(r"预算[改调]?[成为到]?\s*(\d+)")
_PREFERENCE_PATTERN = re.compile(r"偏好[改调]?[成为到]?\s*(.+?)(?:\s|$)")

# 解析编辑操作
def parse_edit_ops(utterance: str, current_itinerary: dict) -> list[PatchOp]:
    """从用户自然语言中解析出结构化 patch 操作列表。"""
    ops: list[PatchOp] = []
    text = utterance.strip()
    # 获取当前行程的天数
    days = current_itinerary.get("days", [])
    # 获取总天数
    total_days = len(days)

    # 提取目标天数
    target_day = _extract_target_day(text, total_days)
    # 提取目标时段
    target_slot = _extract_target_slot(text)

    # 删除操作
    if _match_any(text, _DELETE_HINTS):
        # 如果目标天数和目标时段都存在，则删除目标时段
        if target_day and target_slot:
            ops.append(PatchOp(
                op=PatchOpType.DELETE_SLOT,
                day_index=target_day,
                slot_label=target_slot,
            ))
        # 如果只有目标天数，则删除目标天数所有时段
        elif target_day:
            ops.append(PatchOp(
                op=PatchOpType.DELETE_SLOT,
                day_index=target_day,
                slot_label=None,
            ))
        # 如果删除操作失败，则使用 fallback 操作
        return ops or [_fallback_replace(target_day, target_slot, text)]

    # 插入操作
    if _match_any(text, _ADD_HINTS):
        # 提取插入内容
        new_content = _extract_content_after_hints(text, _ADD_HINTS)
        ops.append(PatchOp(
            op=PatchOpType.INSERT_SLOT,
            # 如果目标天数存在，则插入到目标天数，否则插入到最后一
            day_index=target_day or total_days,
            # 如果目标时段存在，则插入到目标时段，否则插入到晚上
            slot_label=target_slot,
            # 插入内容
            payload={"activity": new_content or "待定活动"},
        ))
        return ops

    # 预算操作
    budget_m = _BUDGET_PATTERN.search(text)
    # 如果预算操作存在，则更新预算
    if budget_m:
        ops.append(PatchOp(
            op=PatchOpType.UPDATE_CONSTRAINT,
            payload={"budget": float(budget_m.group(1))},
        ))

    # 偏好操作
    pref_m = _PREFERENCE_PATTERN.search(text)
    # 如果偏好操作存在，则更新偏好
    if pref_m:
        ops.append(PatchOp(
            op=PatchOpType.UPDATE_CONSTRAINT,
            payload={"preferences": [p.strip() for p in re.split(r"[,，、/+]", pref_m.group(1)) if p.strip()]},
        ))

    # 如果编辑操作存在，则返回编辑操作
    if ops:
        return ops

    # 替换操作
    if _match_any(text, _REPLACE_HINTS):
        # 提取替换内容
        new_content = _extract_content_after_hints(text, _REPLACE_HINTS)
        # 如果目标天数和目标时段都存在，则替换目标时段
        ops.append(PatchOp(
            op=PatchOpType.REPLACE_SLOT,
            day_index=target_day,
            slot_label=target_slot,
            payload={"activity": new_content or "待定活动"},
        ))
        return ops

    # 如果替换操作失败，则使用 fallback 操作
    return [_fallback_replace(target_day, target_slot, text)]


# 应用编辑操作
def apply_patch(
    current_itinerary: dict,
    ops: list[PatchOp],
) -> PatchResult:
    """将 patch 操作列表应用到当前 itinerary，返回新版本。"""
    if not ops:
        return PatchResult(success=False, error="无可执行的编辑操作")

    # 深拷贝当前行程
    itinerary = copy.deepcopy(current_itinerary)
    # 获取旧 revision id
    old_revision_id = itinerary.get("revision_id")
    # 生成新 revision id
    new_revision_id = str(uuid.uuid4())
    # 记录修改的天数
    changed_days: set[int] = set()
    diff_items: list[str] = []
    # 应用编辑操作
    for op in ops:
        try:
            if op.op == PatchOpType.REPLACE_SLOT:
                # 替换操作
                _apply_replace(itinerary, op, changed_days, diff_items)
            elif op.op == PatchOpType.DELETE_SLOT:
                # 删除操作
                _apply_delete(itinerary, op, changed_days, diff_items)
            elif op.op == PatchOpType.INSERT_SLOT:
                # 插入操作
                _apply_insert(itinerary, op, changed_days, diff_items)
            elif op.op == PatchOpType.UPDATE_CONSTRAINT:
                # 更新约束
                _apply_constraint(itinerary, op, diff_items)
        except Exception as e:
            logger.warning(f"Patch op {op.op} failed: {e}")
            # 记录失败操作
            diff_items.append(f"操作 {op.op.value} 执行失败: {str(e)}")

    # 更新行程 revision id
    itinerary["revision_id"] = new_revision_id
    # 更新行程基线 revision id
    itinerary["base_revision_id"] = old_revision_id
    # 更新行程变化摘要
    itinerary["change_summary"] = {
        "changed_days": sorted(changed_days),
        "diff_items": diff_items,
    }

    # 生成解释
    explanation_parts = []
    # 如果修改了天数，则添加修改天数解释
    if changed_days:
        day_str = "、".join(f"第{d}天" for d in sorted(changed_days))
        explanation_parts.append(f"已修改 {day_str}")
    # 如果修改了差异项，则添加修改差异项解释
    if diff_items:
        explanation_parts.append("；".join(diff_items[:3]))
    explanation = "。".join(explanation_parts) + "。" if explanation_parts else "编辑已应用。"

    # 返回编辑结果
    return PatchResult(
        success=True,
        new_itinerary=itinerary,
        old_revision_id=old_revision_id,
        new_revision_id=new_revision_id,
        change_summary={
            "changed_days": sorted(changed_days),
            "diff_items": diff_items,
        },
        explanation=explanation,
    )


# --------------- internal helpers ---------------

def _extract_target_day(text: str, total_days: int) -> int | None:
    m = _DAY_PATTERN.search(text)
    if m:
        d = int(m.group(1))
        return d if 1 <= d <= total_days else None
    return None


def _extract_target_slot(text: str) -> str | None:
    for label in _SLOT_LABELS:
        if label in text:
            return label
    return None


def _match_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(h in text for h in hints)


def _extract_content_after_hints(text: str, hints: tuple[str, ...]) -> str:
    for h in hints:
        idx = text.find(h)
        if idx >= 0:
            rest = text[idx + len(h):].strip()
            rest = re.sub(r"^[为到成]", "", rest).strip()
            if rest:
                return rest
    return ""


def _fallback_replace(day: int | None, slot: str | None, text: str) -> PatchOp:
    clean = re.sub(r"第\s*\d+\s*天", "", text)
    for label in _SLOT_LABELS:
        clean = clean.replace(label, "")
    clean = clean.strip()
    return PatchOp(
        op=PatchOpType.REPLACE_SLOT,
        day_index=day,
        slot_label=slot,
        payload={"activity": clean or "待定活动"},
    )


def _find_day(itinerary: dict, day_index: int) -> dict | None:
    for day in itinerary.get("days", []):
        if day.get("day_index") == day_index:
            return day
    return None


def _find_slot(day: dict, slot_label: str) -> dict | None:
    for slot in day.get("slots", []):
        if slot.get("slot") == slot_label:
            return slot
    return None


def _apply_replace(itinerary: dict, op: PatchOp, changed_days: set, diff_items: list):
    if not op.day_index:
        diff_items.append("未指定修改哪一天，请说明第N天")
        return
    day = _find_day(itinerary, op.day_index)
    if not day:
        diff_items.append(f"未找到第{op.day_index}天")
        return
    changed_days.add(op.day_index)

    if op.slot_label:
        slot = _find_slot(day, op.slot_label)
        if slot:
            old_activity = slot.get("activity", "")
            new_activity = op.payload.get("activity", old_activity)
            slot["activity"] = new_activity
            if "place" in op.payload:
                slot["place"] = op.payload["place"]
            diff_items.append(f"第{op.day_index}天{op.slot_label}：「{old_activity}」→「{new_activity}」")
        else:
            diff_items.append(f"未找到第{op.day_index}天的{op.slot_label}时段")
    else:
        first_slot = day.get("slots", [None])[0]
        if first_slot:
            old_activity = first_slot.get("activity", "")
            new_activity = op.payload.get("activity", old_activity)
            first_slot["activity"] = new_activity
            diff_items.append(f"第{op.day_index}天首个时段：「{old_activity}」→「{new_activity}」")


def _apply_delete(itinerary: dict, op: PatchOp, changed_days: set, diff_items: list):
    if not op.day_index:
        diff_items.append("未指定删除哪一天，请说明第N天")
        return
    day = _find_day(itinerary, op.day_index)
    if not day:
        diff_items.append(f"未找到第{op.day_index}天")
        return
    changed_days.add(op.day_index)

    if op.slot_label:
        slots = day.get("slots", [])
        original_len = len(slots)
        day["slots"] = [s for s in slots if s.get("slot") != op.slot_label]
        if len(day["slots"]) < original_len:
            diff_items.append(f"已删除第{op.day_index}天{op.slot_label}时段")
        else:
            diff_items.append(f"未找到第{op.day_index}天的{op.slot_label}时段")
        if not day["slots"]:
            day["slots"] = [{"slot": "上午", "activity": "自由活动", "place": None, "transit": None}]
            diff_items.append(f"第{op.day_index}天已无时段，保留默认自由活动")
    else:
        removed_activities = [s.get("activity", "") for s in day.get("slots", [])]
        day["slots"] = [{"slot": "上午", "activity": "自由活动", "place": None, "transit": None}]
        diff_items.append(f"已清空第{op.day_index}天所有时段（原有：{'、'.join(removed_activities)}）")


def _apply_insert(itinerary: dict, op: PatchOp, changed_days: set, diff_items: list):
    day_index = op.day_index or len(itinerary.get("days", [])) or 1
    day = _find_day(itinerary, day_index)
    if not day:
        diff_items.append(f"未找到第{day_index}天，无法插入")
        return
    changed_days.add(day_index)

    new_slot = {
        "slot": op.slot_label or "晚上",
        "activity": op.payload.get("activity", "待定活动"),
        "place": op.payload.get("place"),
        "transit": op.payload.get("transit"),
    }
    day.get("slots", []).append(new_slot)
    diff_items.append(f"第{day_index}天新增{new_slot['slot']}时段：{new_slot['activity']}")


def _apply_constraint(itinerary: dict, op: PatchOp, diff_items: list):
    profile = itinerary.get("trip_profile", {})
    constraints = profile.get("constraints", {})
    budget_summary = itinerary.get("budget_summary", {})

    if "budget" in op.payload:
        new_budget = op.payload["budget"]
        old_budget = budget_summary.get("total_estimate", 0)
        budget_summary["total_estimate"] = new_budget
        constraints["budget_range"] = f"约 {int(new_budget)} 元"
        diff_items.append(f"预算：{int(old_budget)} → {int(new_budget)} 元")

    if "preferences" in op.payload:
        old_prefs = constraints.get("preferences", [])
        new_prefs = op.payload["preferences"]
        constraints["preferences"] = new_prefs
        diff_items.append(f"偏好：{'、'.join(old_prefs) or '无'} → {'、'.join(new_prefs)}")

    profile["constraints"] = constraints
    itinerary["trip_profile"] = profile
    itinerary["budget_summary"] = budget_summary
