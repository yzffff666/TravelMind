from dataclasses import dataclass


@dataclass(frozen=True)
class TravelApiRules:
    """Travel API constants: event names and user-facing fallback texts."""

    event_intent_routed: str = "intent_routed"
    event_final_text: str = "final_text"
    event_final_itinerary: str = "final_itinerary"
    event_stage_start: str = "stage_start"
    event_stage_progress: str = "stage_progress"
    event_error: str = "error"
    event_reset_done: str = "reset_done"

    text_reset_done: str = "已为当前会话重置行程状态，你可以重新输入新的出行需求。"
    text_need_itinerary_for_edit: str = "当前会话还没有可编辑的行程，请先描述目的地、天数和预算生成草案。"
    text_qa_placeholder: str = "已识别问答意图，下一步将接入行程问答分支（T-M2-011 后续增强）。"
    text_generate_fallback: str = "未能生成结构化草案，请补充目的地、天数和预算后重试。"
    text_generate_error: str = "草案生成失败，请稍后再试。"

    upload_image_root: str = "uploads/images"
    upload_timestamp_format: str = "%Y%m%d_%H%M%S"


TRAVEL_API_RULES = TravelApiRules()
