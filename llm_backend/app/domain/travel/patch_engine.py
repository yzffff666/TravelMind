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
    # 重新规划某一天
    REPLAN_DAY = "replan_day"
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


_DAY_PATTERN = re.compile(r"第\s*(\d+|[一二两三四五六七八九十]+)\s*天")
_CN_DAY_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_SLOT_LABELS = ("上午", "下午", "晚上")

# 将常见 slot 变体规范化到标准三档
_SLOT_NORMALIZE: dict[str, str] = {
    "上午": "上午", "早上": "上午", "早晨": "上午", "早": "上午", "morning": "上午",
    "下午": "下午", "中午": "下午", "午后": "下午", "午间": "下午", "afternoon": "下午",
    "晚上": "晚上", "夜晚": "晚上", "夜间": "晚上", "傍晚": "晚上", "夜": "晚上", "evening": "晚上",
}

def _normalize_slot(label: str | None) -> str | None:
    if not label:
        return None
    return _SLOT_NORMALIZE.get(label, label)

_DELETE_HINTS = ("删掉", "删除", "去掉", "不要", "取消")
_ADD_HINTS = ("增加", "加上", "添加", "插入", "新增")
_REPLACE_HINTS = ("换成", "替换", "改成", "改为", "变成")
_DAY_REPLAN_HINTS = (*_REPLACE_HINTS, "安排", "调整", "调整为", "改一下", "换一下")
_MUTATION_HINTS = (
    *_DELETE_HINTS,
    *_ADD_HINTS,
    *_REPLACE_HINTS,
    "修改",
    "调整",
    "改一下",
    "换一下",
    "别太",
    "不要太",
    "预算",
    "偏好",
)
_BUDGET_PATTERN = re.compile(r"预算[改调]?[成为到]?\s*(\d+)")
_PREFERENCE_PATTERN = re.compile(r"偏好[改调]?[成为到]?\s*(.+?)(?:\s|$)")
_DAY_REPLAN_CONSTRAINT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "indoor": ("室内", "下雨", "避雨", "少晒", "不晒", "博物馆", "美术馆", "展馆", "商场"),
    "relaxed": ("轻松", "悠闲", "慢一点", "慢节奏", "少走路", "别太累", "不要太累", "别太赶", "不要太赶", "不赶"),
    "food": ("美食", "吃喝", "逛吃", "小吃", "茶餐厅", "餐厅"),
    "culture": ("文化", "历史", "人文", "艺术", "展览"),
}
_READONLY_DAY_QUESTION_HINTS = (
    "是什么",
    "有什么",
    "去哪里",
    "去哪",
    "哪里",
    "怎么安排",
    "安排呢",
    "有没有",
    "有无",
    "是否",
    "吗",
    "？",
    "?",
)
_PLACE_TRAILING_ACTIONS = (
    "游玩",
    "游览",
    "参观",
    "逛逛",
    "逛",
    "打卡",
    "散步",
    "用餐",
    "吃饭",
    "体验",
)


def has_mutation_intent(utterance: str) -> bool:
    """Return whether the utterance explicitly asks to write/change itinerary state."""
    text = (utterance or "").strip()
    return bool(text) and (
        any(hint in text for hint in _MUTATION_HINTS)
        or _has_contextual_day_replan_intent(text)
    )

# 解析编辑操作
def parse_edit_ops(utterance: str, current_itinerary: dict) -> list[PatchOp]:
    """从用户自然语言中解析出结构化 patch 操作列表。"""
    ops: list[PatchOp] = []
    text = utterance.strip()
    if _is_readonly_day_question(text):
        return []
    # 获取当前行程的天数
    days = current_itinerary.get("days", [])
    # 获取总天数
    total_days = len(days)

    # 提取目标天数
    target_day = _extract_target_day(text, total_days)
    # 提取目标时段
    target_slot = _extract_target_slot(text)

    # Collect all matching ops (no early return — supports multi-op edits)

    day_replan_constraints = _extract_day_replan_constraints(text)
    # Constraint edits are replan requests even when they name a specific
    # slot. A generic text replacement would leak phrases such as "改成室内"
    # into the itinerary instead of selecting a verified POI. Explicit add /
    # delete commands retain their own semantics.
    if (
        target_day
        and day_replan_constraints
        and has_mutation_intent(text)
        and not _match_any(text, _DELETE_HINTS)
        and not _match_any(text, _ADD_HINTS)
    ):
        ops.append(PatchOp(
            op=PatchOpType.REPLAN_DAY,
            day_index=target_day,
            payload={
                "constraints": day_replan_constraints,
                "raw_request": text,
                "target_slot": target_slot,
            },
        ))

    if _match_any(text, _DELETE_HINTS):
        if target_day and target_slot:
            ops.append(PatchOp(
                op=PatchOpType.DELETE_SLOT,
                day_index=target_day,
                slot_label=target_slot,
            ))
        elif target_day:
            ops.append(PatchOp(
                op=PatchOpType.DELETE_SLOT,
                day_index=target_day,
                slot_label=None,
            ))

    if _match_any(text, _ADD_HINTS):
        new_content = _extract_content_after_hints(text, _ADD_HINTS)
        ops.append(PatchOp(
            op=PatchOpType.INSERT_SLOT,
            day_index=target_day or total_days,
            slot_label=target_slot,
            payload={"activity": new_content or "待定活动"},
        ))

    budget_m = _BUDGET_PATTERN.search(text)
    if budget_m:
        ops.append(PatchOp(
            op=PatchOpType.UPDATE_CONSTRAINT,
            payload={"budget": float(budget_m.group(1))},
        ))

    pref_m = _PREFERENCE_PATTERN.search(text)
    if pref_m:
        ops.append(PatchOp(
            op=PatchOpType.UPDATE_CONSTRAINT,
            payload={"preferences": [p.strip() for p in re.split(r"[,，、/+]", pref_m.group(1)) if p.strip()]},
        ))

    if not ops and _match_any(text, _REPLACE_HINTS):
        new_content = _extract_content_after_hints(text, _REPLACE_HINTS)
        ops.append(PatchOp(
            op=PatchOpType.REPLACE_SLOT,
            day_index=target_day,
            slot_label=target_slot,
            payload={"activity": new_content or "待定活动"},
        ))

    if not ops:
        ops.append(_fallback_replace(target_day, target_slot, text))

    return ops


# 应用编辑操作
def apply_patch(
    current_itinerary: dict,
    ops: list[PatchOp],
) -> PatchResult:
    """将 patch 操作列表应用到当前 itinerary，返回新版本。"""
    if not ops:
        return PatchResult(success=False, error="无可执行的编辑操作")

    itinerary = copy.deepcopy(current_itinerary)
    old_revision_id = itinerary.get("revision_id")
    new_revision_id = str(uuid.uuid4())
    changed_days: set[int] = set()
    diff_items: list[str] = []
    replan_requests: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    for op in ops:
        try:
            applied = False
            if op.op == PatchOpType.REPLACE_SLOT:
                applied = _apply_replace(itinerary, op, changed_days, diff_items)
            elif op.op == PatchOpType.DELETE_SLOT:
                applied = _apply_delete(itinerary, op, changed_days, diff_items)
            elif op.op == PatchOpType.INSERT_SLOT:
                applied = _apply_insert(itinerary, op, changed_days, diff_items)
            elif op.op == PatchOpType.REPLAN_DAY:
                applied = _apply_replan_day(itinerary, op, changed_days, diff_items, replan_requests)
            elif op.op == PatchOpType.UPDATE_CONSTRAINT:
                applied = _apply_constraint(itinerary, op, diff_items)
            if applied:
                succeeded += 1
            else:
                failed += 1
        except Exception as e:
            logger.warning(f"Patch op {op.op} failed: {e}")
            diff_items.append(f"操作 {op.op.value} 执行失败: {str(e)}")
            failed += 1

    if succeeded <= 0:
        error = "；".join(diff_items) if diff_items else "编辑未命中任何行程内容"
        return PatchResult(
            success=False,
            change_summary={
                "changed_days": [],
                "diff_items": diff_items,
                "failed_ops": failed,
            },
            explanation=error,
            error=error,
        )

    # 更新行程 revision id
    itinerary["revision_id"] = new_revision_id
    # 更新行程基线 revision id
    itinerary["base_revision_id"] = old_revision_id
    # 更新行程变化摘要
    itinerary["change_summary"] = {
        "changed_days": sorted(changed_days),
        "diff_items": diff_items,
        "failed_ops": failed,
        "replan_requests": replan_requests,
    }
    _recompute_lightweight_coverage(itinerary)

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

    return PatchResult(
        success=succeeded > 0,
        new_itinerary=itinerary,
        old_revision_id=old_revision_id,
        new_revision_id=new_revision_id,
        change_summary={
            "changed_days": sorted(changed_days),
            "diff_items": diff_items,
            "failed_ops": failed,
            "replan_requests": replan_requests,
        },
        explanation=explanation,
    )


# --------------- internal helpers ---------------

def _extract_target_day(text: str, total_days: int) -> int | None:
    m = _DAY_PATTERN.search(text)
    if m:
        raw = m.group(1)
        d = int(raw) if raw.isdigit() else _cn_day_to_int(raw)
        return d if 1 <= d <= total_days else None
    return None


def _cn_day_to_int(raw: str) -> int:
    if raw in _CN_DAY_NUM:
        return _CN_DAY_NUM[raw]
    if raw.startswith("十") and len(raw) == 2:
        return 10 + _CN_DAY_NUM.get(raw[1], 0)
    if raw.endswith("十") and len(raw) == 2:
        return _CN_DAY_NUM.get(raw[0], 1) * 10
    if len(raw) == 3 and raw[1] == "十":
        return _CN_DAY_NUM.get(raw[0], 0) * 10 + _CN_DAY_NUM.get(raw[2], 0)
    return 0


def _extract_target_slot(text: str) -> str | None:
    for variant, canonical in _SLOT_NORMALIZE.items():
        if variant in text:
            return canonical
    return None


def _extract_day_replan_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    for constraint, keywords in _DAY_REPLAN_CONSTRAINT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            constraints.append(constraint)
    return constraints


def _has_contextual_day_replan_intent(text: str) -> bool:
    if not _DAY_PATTERN.search(text):
        return False
    if _is_readonly_day_question(text):
        return False
    if not _extract_day_replan_constraints(text):
        return False
    return any(action in text for action in ("改", "换", "安排", "调整", "重排", "重新规划"))


def _is_readonly_day_question(text: str) -> bool:
    return bool(_DAY_PATTERN.search(text)) and any(hint in text for hint in _READONLY_DAY_QUESTION_HINTS)


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


def _infer_place_from_activity(activity: str) -> str | None:
    place = (activity or "").strip(" ，,。")
    place = re.sub(r"^(去|到|前往|游览|参观|逛|打卡|体验)", "", place).strip(" ，,。")
    for suffix in _PLACE_TRAILING_ACTIONS:
        if place.endswith(suffix) and len(place) > len(suffix):
            place = place[: -len(suffix)].strip(" ，,。")
            break
    return place or None


def _clear_slot_verification(slot: dict) -> None:
    """After a manual replacement, old geo/evidence no longer verifies the new activity."""
    slot.pop("transit", None)
    slot.pop("location", None)
    slot.pop("image_url", None)
    slot.pop("cost_breakdown", None)
    slot.pop("risk", None)
    slot["alternatives"] = []
    slot["evidence_refs"] = []


def _recompute_lightweight_coverage(itinerary: dict) -> None:
    slots = [
        slot
        for day in itinerary.get("days", [])
        for slot in day.get("slots", [])
    ]
    if not slots:
        return
    covered = sum(1 for slot in slots if slot.get("evidence_refs"))
    validation = itinerary.setdefault("validation", {})
    validation["coverage_score"] = round(covered / len(slots), 4)


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
    target = _normalize_slot(slot_label)
    for slot in day.get("slots", []):
        if _normalize_slot(slot.get("slot")) == target:
            return slot
    return None


def _apply_replace(itinerary: dict, op: PatchOp, changed_days: set, diff_items: list) -> bool:
    if not op.day_index:
        diff_items.append("未指定修改哪一天，请说明第N天")
        return False
    day = _find_day(itinerary, op.day_index)
    if not day:
        diff_items.append(f"未找到第{op.day_index}天")
        return False

    if op.slot_label:
        slot = _find_slot(day, op.slot_label)
        if slot:
            old_activity = slot.get("activity", "")
            new_activity = op.payload.get("activity", old_activity)
            slot["activity"] = new_activity
            slot["place"] = op.payload.get("place") or _infer_place_from_activity(new_activity)
            _clear_slot_verification(slot)
            diff_items.append(f"第{op.day_index}天{op.slot_label}：「{old_activity}」→「{new_activity}」")
            changed_days.add(op.day_index)
            return True
        else:
            diff_items.append(f"未找到第{op.day_index}天的{op.slot_label}时段")
            return False
    else:
        first_slot = day.get("slots", [None])[0]
        if first_slot:
            old_activity = first_slot.get("activity", "")
            new_activity = op.payload.get("activity", old_activity)
            first_slot["activity"] = new_activity
            first_slot["place"] = op.payload.get("place") or _infer_place_from_activity(new_activity)
            _clear_slot_verification(first_slot)
            diff_items.append(f"第{op.day_index}天首个时段：「{old_activity}」→「{new_activity}」")
            changed_days.add(op.day_index)
            return True
        diff_items.append(f"第{op.day_index}天没有可修改的时段")
        return False


def _apply_delete(itinerary: dict, op: PatchOp, changed_days: set, diff_items: list) -> bool:
    if not op.day_index:
        diff_items.append("未指定删除哪一天，请说明第N天")
        return False
    day = _find_day(itinerary, op.day_index)
    if not day:
        diff_items.append(f"未找到第{op.day_index}天")
        return False

    if op.slot_label:
        slots = day.get("slots", [])
        original_len = len(slots)
        target_slot = _normalize_slot(op.slot_label)
        day["slots"] = [
            s for s in slots
            if _normalize_slot(s.get("slot")) != target_slot
        ]
        if len(day["slots"]) < original_len:
            diff_items.append(f"已删除第{op.day_index}天{op.slot_label}时段")
            changed_days.add(op.day_index)
        else:
            diff_items.append(f"未找到第{op.day_index}天的{op.slot_label}时段")
            return False
        if not day["slots"]:
            day["slots"] = [{"slot": "上午", "activity": "自由活动", "place": None, "transit": None}]
            diff_items.append(f"第{op.day_index}天已无时段，保留默认自由活动")
        return True
    else:
        removed_activities = [s.get("activity", "") for s in day.get("slots", [])]
        day["slots"] = [{"slot": "上午", "activity": "自由活动", "place": None, "transit": None}]
        diff_items.append(f"已清空第{op.day_index}天所有时段（原有：{'、'.join(removed_activities)}）")
        changed_days.add(op.day_index)
        return True


def _apply_insert(itinerary: dict, op: PatchOp, changed_days: set, diff_items: list) -> bool:
    day_index = op.day_index or len(itinerary.get("days", [])) or 1
    day = _find_day(itinerary, day_index)
    if not day:
        diff_items.append(f"未找到第{day_index}天，无法插入")
        return False
    changed_days.add(day_index)

    new_slot = {
        "slot": op.slot_label or "晚上",
        "activity": op.payload.get("activity", "待定活动"),
        "place": op.payload.get("place"),
        "transit": op.payload.get("transit"),
    }
    day.get("slots", []).append(new_slot)
    diff_items.append(f"第{day_index}天新增{new_slot['slot']}时段：{new_slot['activity']}")
    return True


def _apply_replan_day(
    itinerary: dict,
    op: PatchOp,
    changed_days: set,
    diff_items: list,
    replan_requests: list[dict[str, Any]],
) -> bool:
    if not op.day_index:
        diff_items.append("未指定重新规划哪一天，请说明第N天")
        return False
    day = _find_day(itinerary, op.day_index)
    if not day:
        diff_items.append(f"未找到第{op.day_index}天")
        return False

    constraints = list(op.payload.get("constraints") or [])
    target_slot = _normalize_slot(op.payload.get("target_slot"))
    target_slots = day.get("slots", [])
    if target_slot:
        slot = _find_slot(day, target_slot)
        if slot is None:
            diff_items.append(f"未找到第{op.day_index}天的{target_slot}时段")
            return False
        target_slots = [slot]
    old_slots = [slot.get("activity", "") for slot in target_slots]
    anchor_locations = _slot_anchor_locations(target_slots)

    # Candidate-driven replan is transactional at the API boundary. Do not
    # replace the existing day with a template here: if recall/planning cannot
    # produce verified POIs, the caller can return a clarification with no new
    # revision instead of persisting a placeholder itinerary.
    changed_days.add(op.day_index)
    replan_requests.append({
        "day_index": op.day_index,
        "constraints": constraints,
        "raw_request": op.payload.get("raw_request"),
        "anchor_locations": anchor_locations,
        "target_slot": target_slot,
        "execution_source": op.payload.get("execution_source") or "rule",
    })

    old_desc = "、".join([s for s in old_slots if s][:3]) or "原安排"
    constraint_desc = "、".join(_constraint_label(c) for c in constraints) or "新偏好"
    scope_desc = f"{target_slot}时段" if target_slot else ""
    diff_items.append(f"第{op.day_index}天{scope_desc}按「{constraint_desc}」候选重新规划（原安排：{old_desc}）")
    return True


def _slot_anchor_locations(slots: list[dict]) -> list[dict[str, float]]:
    anchors: list[dict[str, float]] = []
    for slot in slots:
        location = slot.get("location") or {}
        try:
            lat = float(location.get("lat"))
            lng = float(location.get("lng"))
        except (TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            anchors.append({"lat": lat, "lng": lng})
    return anchors


def _constraint_label(constraint: str) -> str:
    labels = {
        "indoor": "室内",
        "relaxed": "轻松",
        "food": "美食",
        "culture": "文化",
    }
    return labels.get(constraint, constraint)


def _apply_constraint(itinerary: dict, op: PatchOp, diff_items: list) -> bool:
    profile = itinerary.get("trip_profile", {})
    constraints = profile.get("constraints", {})
    budget_summary = itinerary.get("budget_summary", {})
    modified = False

    if "budget" in op.payload:
        new_budget = op.payload["budget"]
        old_budget = budget_summary.get("total_estimate", 0)
        budget_summary["total_estimate"] = new_budget
        constraints["budget_range"] = f"约 {int(new_budget)} 元"
        diff_items.append(f"预算：{int(old_budget)} → {int(new_budget)} 元")
        modified = True

    if "preferences" in op.payload:
        old_prefs = constraints.get("preferences", [])
        new_prefs = op.payload["preferences"]
        constraints["preferences"] = new_prefs
        diff_items.append(f"偏好：{'、'.join(old_prefs) or '无'} → {'、'.join(new_prefs)}")
        modified = True

    profile["constraints"] = constraints
    itinerary["trip_profile"] = profile
    itinerary["budget_summary"] = budget_summary
    if not modified:
        diff_items.append("未识别到可更新的约束")
    return modified
