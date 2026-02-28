from app.domain.travel.draft_rules import DRAFT_CONFIG, DraftConfig
from app.schemas.itinerary_v1 import ItinerarySlot

# 提取天数
def extract_days(query: str, config: DraftConfig = DRAFT_CONFIG) -> int | None:
    match = config.days_pattern.search(query)
    if not match:
        return None
    return max(config.min_days, min(int(match.group(1)), config.max_days))

# 提取预算
def extract_budget(query: str, config: DraftConfig = DRAFT_CONFIG) -> float | None:
    match = config.budget_pattern.search(query)
    if not match:
        return None
    return max(float(match.group(1)), 0.0)

# 提取目的地城市
def extract_destination(query: str, config: DraftConfig = DRAFT_CONFIG) -> str | None:
    for pattern in config.destination_patterns:
        match = pattern.search(query)
        if match:
            return match.group(1)
    return None


def extract_traveler_type(query: str, config: DraftConfig = DRAFT_CONFIG) -> str | None:
    for value in config.traveler_keywords:
        if value in query:
            return value
    return None

# 构建时段
def build_slots(day_index: int, config: DraftConfig = DRAFT_CONFIG) -> list[ItinerarySlot]:
    return [
        ItinerarySlot(slot=slot_name, activity=activity_template.format(day=day_index))
        for slot_name, activity_template in config.day_slot_templates
    ]

