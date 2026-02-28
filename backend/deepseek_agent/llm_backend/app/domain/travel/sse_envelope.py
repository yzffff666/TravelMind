import json
from datetime import datetime, timezone
from typing import Optional

# 获取UTC时间戳
def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


# 构建数据行
def build_data_line(payload: object) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 构建事件行
def build_event_line(event: str, data: dict) -> str:
    return f"event: {event}\n" + build_data_line(data)


# 构建事件封装
def build_event_envelope(
    *,
    request_id: str,
    conversation_id: str,
    revision_id: Optional[str],
    payload: dict,
) -> dict:
    return {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "revision_id": revision_id,
        "timestamp": utc_timestamp(),
        "payload": payload,
    }

