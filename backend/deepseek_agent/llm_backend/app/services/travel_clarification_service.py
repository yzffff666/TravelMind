import json
import re
from typing import Any, Dict, List, Tuple

from app.domain.travel.clarification_rules import (
    CLARIFICATION_STAGE_NAME,
    CLARIFICATION_MSG_HARD_AND_SOFT,
    CLARIFICATION_MSG_HARD_ONLY,
    CONSTRAINT_PATTERNS,
    FIELD_LABELS,
    HARD_REQUIRED_FIELDS,
    SOFT_RECOMMENDED_FIELDS,
    SSE_EVENT_STAGE_PROGRESS,
    SSE_EVENT_STAGE_START,
)

# 旅行澄清服务
class TravelClarificationService:
    """Handle clarification gate and in-memory pending clarification state."""

    def __init__(self) -> None:
        # thread_id -> pending clarification context
        # 说明：当前实现是“进程内内存态”，服务重启后不会保留。
        self._pending: Dict[str, Dict[str, Any]] = {}

    def has_pending(self, thread_id: str) -> bool:
        # 判断指定会话是否仍处于“等待补充约束”的阶段。
        return thread_id in self._pending

    def clear_pending(self, thread_id: str) -> None:
        # reset 场景：显式清理会话的澄清中间态。
        self._pending.pop(thread_id, None)

    def start_new(self, thread_id: str, query: str) -> Dict[str, Any]:
        # 第一次进入会话时做约束抽取与缺失判断。
        constraints = self._extract_constraint_presence(query)
        missing_hard = self._missing_fields(constraints, HARD_REQUIRED_FIELDS)
        missing_soft = self._missing_fields(constraints, SOFT_RECOMMENDED_FIELDS)

        if missing_hard:
            # 仅在硬门槛缺失时记录 pending，后续由 resume 继续补充。
            self._pending[thread_id] = {
                "initial_query": query,
                "constraints": constraints,
                "followups": [],
            }

        # 返回是否需要澄清以及缺失的硬门槛和软门槛。
        return {
            "need_clarification": bool(missing_hard),
            "missing_hard": missing_hard,
            "missing_soft": missing_soft,
        }

    # 续答阶段：把本轮补充信息和历史已识别约束做“并集”。
    def continue_pending(self, thread_id: str, query: str) -> Dict[str, Any]:
        # 获取历史约束和本轮补充的约束。
        pending = self._pending.get(thread_id)
        # 如果历史约束和本轮补充的约束为空，则返回False。
        if not pending:
            return {"has_pending": False}

        # 提取本轮补充的约束。
        delta = self._extract_constraint_presence(query)
        # 合并历史约束和本轮补充的约束。
        merged = self._merge_constraint_presence(pending["constraints"], delta)
        # 计算缺失的硬门槛和软门槛。
        missing_hard = self._missing_fields(merged, HARD_REQUIRED_FIELDS)
        missing_soft = self._missing_fields(merged, SOFT_RECOMMENDED_FIELDS)

        # 更新历史约束和本轮补充的约束。
        pending["constraints"] = merged
        pending["followups"].append(query)

        if missing_hard:
            # 仍缺硬门槛：继续要求澄清。
            return {
                "has_pending": True,
                "need_clarification": True,
                "missing_hard": missing_hard,
                "missing_soft": missing_soft,
            }

        # 硬门槛补齐后：合并初始 query + 补充信息，交还给主规划流程。
        combined_query = pending["initial_query"]
        if pending["followups"]:
            combined_query = f"{combined_query}\n补充信息：{'；'.join(pending['followups'])}"
        # 澄清结束，清理 pending 状态，避免后续重复进入澄清分支。
        self._pending.pop(thread_id, None)
        return {
            "has_pending": True,
            "need_clarification": False,
            "combined_query": combined_query,
        }

    def build_clarification_payload(self, missing_hard: List[str], missing_soft: List[str]) -> Dict[str, Any]:
        """Build structured clarification payload for SSE envelope."""
        clarification_text = self._build_clarification_message(missing_hard, missing_soft)
        return {
            "stage": CLARIFICATION_STAGE_NAME,
            "missing_required": missing_hard,
            "missing_optional": missing_soft,
            "message": clarification_text,
        }

    def build_clarification_stream(self, thread_id: str, missing_hard: List[str], missing_soft: List[str]):
        # 将澄清结果包装成 SSE 事件流，供前端实时显示。
        payload = self.build_clarification_payload(missing_hard=missing_hard, missing_soft=missing_soft)
        clarification_text = payload["message"]

        async def _stream():
            # Structured events for new clients.
            # 1. 触发澄清阶段开始事件。
            yield self._sse_line(
                {
                    "event": SSE_EVENT_STAGE_START,
                    "stage": CLARIFICATION_STAGE_NAME,
                    "conversation_id": thread_id,
                }
            )
            # 2. 触发澄清阶段进度事件。
            yield self._sse_line(
                {
                    "event": SSE_EVENT_STAGE_PROGRESS,
                    "stage": payload["stage"],
                    "conversation_id": thread_id,
                    "missing_required": payload["missing_required"],
                    "missing_optional": payload["missing_optional"],
                    "message": payload["message"],
                }
            )
            # Text fallback for old clients.
            # 3. 触发澄清阶段完成事件。
            yield self._sse_line(clarification_text)

        return _stream()

    def _extract_constraint_presence(self, text: str) -> Dict[str, bool]:
        """Heuristic extraction from externalized rule definitions."""
        # 基于规则库做“有/无”识别（不是实体抽取，不输出具体值）。
        normalized = (text or "").strip()
        result: Dict[str, bool] = {}
        for field, patterns in CONSTRAINT_PATTERNS.items():
            result[field] = any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns)
        return result

    def _merge_constraint_presence(self, base: Dict[str, bool], delta: Dict[str, bool]) -> Dict[str, bool]:
        # 只要历史或本轮任一命中，该字段就记为 True。
        return {key: bool(base.get(key)) or bool(delta.get(key)) for key in FIELD_LABELS.keys()}

    @staticmethod
    def _missing_fields(constraints: Dict[str, bool], keys: Tuple[str, ...]) -> List[str]:
        # 返回给定字段集合中仍未满足的字段列表。
        return [key for key in keys if not constraints.get(key, False)]

    def _build_clarification_message(self, missing_hard: List[str], missing_soft: List[str]) -> str:
        # 将缺失字段映射为自然语言提示，给前端直接展示。
        hard_text = "、".join(FIELD_LABELS[key] for key in missing_hard)
        if missing_soft:
            soft_text = "、".join(FIELD_LABELS[key] for key in missing_soft)
            return CLARIFICATION_MSG_HARD_AND_SOFT.format(
                hard_text=hard_text,
                soft_text=soft_text,
            )
        return CLARIFICATION_MSG_HARD_ONLY.format(hard_text=hard_text)

    @staticmethod
    def _sse_line(payload: Any) -> str:
        # SSE 标准格式：每个消息块以 data: 开头，以空行结束。
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
