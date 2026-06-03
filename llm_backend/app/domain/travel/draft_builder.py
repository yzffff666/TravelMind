import re

from app.domain.travel.draft_rules import DRAFT_CONFIG, DraftConfig
from app.schemas.itinerary_v1 import ItinerarySlot

_CN_NUM = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_CN_WEEK_PATTERN = re.compile(r"([一二两三四五六七八九十])\s*周")
_CN_DAY_PATTERN = re.compile(r"([一二两三四五六七八九十]+)\s*[天日]")
_DIGIT_WEEK_PATTERN = re.compile(r"(\d+)\s*周")
_HALF_MONTH_PATTERN = re.compile(r"半个?月")


def _cn_to_int(cn: str) -> int | None:
    if len(cn) == 1:
        return _CN_NUM.get(cn)
    if len(cn) == 2 and cn[0] == "十":
        return 10 + _CN_NUM.get(cn[1], 0)
    if len(cn) == 2 and cn[1] == "十":
        return _CN_NUM.get(cn[0], 1) * 10
    return _CN_NUM.get(cn)


def extract_days(query: str, config: DraftConfig = DRAFT_CONFIG) -> int | None:
    match = config.days_pattern.search(query)
    if match:
        return max(config.min_days, min(int(match.group(1)), config.max_days))

    m = _DIGIT_WEEK_PATTERN.search(query)
    if m:
        return max(config.min_days, min(int(m.group(1)) * 7, config.max_days))

    m = _CN_WEEK_PATTERN.search(query)
    if m:
        weeks = _CN_NUM.get(m.group(1), 1)
        return max(config.min_days, min(weeks * 7, config.max_days))

    m = _CN_DAY_PATTERN.search(query)
    if m:
        days = _cn_to_int(m.group(1))
        if days:
            return max(config.min_days, min(days, config.max_days))

    if _HALF_MONTH_PATTERN.search(query):
        return max(config.min_days, min(15, config.max_days))

    return None


_CN_BUDGET_PATTERN = re.compile(r"([一二两三四五六七八九十]+)\s*(万|千)")
_DIGIT_WAN_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*万")
_DIGIT_W_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[wW]")
_DIGIT_K_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[kK]")
_DIGIT_YUAN_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块钱?)")
_PER_PERSON_BUDGET_PATTERN = re.compile(
    r"(?:人均|每人|每个人|per\s*person)\s*(?:预算|花费|消费|费用|budget|cost)?\s*[:：]?\s*(\d{3,6}(?:\.\d+)?)\s*(?:元|块钱?|rmb|cny|港币|hkd)?",
    re.I,
)
_SLASH_PERSON_BUDGET_PATTERN = re.compile(
    r"(\d{3,6}(?:\.\d+)?)\s*(?:元|块钱?|rmb|cny|港币|hkd)?\s*/\s*(?:人|person|pax)",
    re.I,
)
_LOCAL_SPEND_BUDGET_PATTERN = re.compile(
    r"(?:当地|当地花销|当地消费|纯玩|游玩|不含(?:机票|交通|住宿|酒店|往返|大交通|机票住宿){1,4})\s*(?:预算|花费|消费|费用)?\s*[:：]?\s*(\d{3,6}(?:\.\d+)?)\s*(?:元|块钱?|rmb|cny|港币|hkd)?",
    re.I,
)
_BUDGET_CONTEXT_PATTERN = re.compile(r"(\d{3,}(?:\.\d+)?)\s*(?:左右|以内|以下|上下|出头|多(?!少))")
_BUDGET_RANGE_PATTERN = re.compile(r"(\d{3,6})\s*[-~到至]\s*(\d{3,6})")
_STANDALONE_BUDGET_PATTERN = re.compile(r"^\s*(\d{3,6})(?:\.0+)?\s*$")
_QUALITATIVE_BUDGETS = (
    (("经济", "省钱", "低预算", "穷游"), 3000.0),
    (("中等", "适中", "中档", "普通预算"), 6000.0),
    (("高预算", "宽松预算", "豪华", "品质"), 12000.0),
)


def extract_budget(query: str, config: DraftConfig = DRAFT_CONFIG) -> float | None:
    normalized = (query or "").strip()
    # Budget ranges should be interpreted as a concrete midpoint before the
    # generic budget pattern captures only the lower bound.
    m = _BUDGET_RANGE_PATTERN.search(query)
    if m:
        low = float(m.group(1))
        high = float(m.group(2))
        if high < low:
            low, high = high, low
        return max((low + high) / 2.0, 0.0)

    match = config.budget_pattern.search(query)
    if match:
        return max(float(match.group(1)), 0.0)

    m = _DIGIT_W_PATTERN.search(query)
    if m:
        return max(float(m.group(1)) * 10000, 0.0)

    m = _DIGIT_K_PATTERN.search(query)
    if m:
        return max(float(m.group(1)) * 1000, 0.0)

    m = _DIGIT_YUAN_PATTERN.search(query)
    if m:
        return max(float(m.group(1)), 0.0)

    m = _PER_PERSON_BUDGET_PATTERN.search(query)
    if m:
        return max(float(m.group(1)), 0.0)

    m = _SLASH_PERSON_BUDGET_PATTERN.search(query)
    if m:
        return max(float(m.group(1)), 0.0)

    m = _LOCAL_SPEND_BUDGET_PATTERN.search(query)
    if m:
        return max(float(m.group(1)), 0.0)

    m = _DIGIT_WAN_PATTERN.search(query)
    if m:
        return max(float(m.group(1)) * 10000, 0.0)

    m = _CN_BUDGET_PATTERN.search(query)
    if m:
        num = _cn_to_int(m.group(1))
        unit = m.group(2)
        if num:
            multiplier = 10000 if unit == "万" else 1000
            return max(float(num * multiplier), 0.0)

    m = _BUDGET_CONTEXT_PATTERN.search(query)
    if m:
        return max(float(m.group(1)), 0.0)

    m = _STANDALONE_BUDGET_PATTERN.match(normalized)
    if m:
        return max(float(m.group(1)), 0.0)

    if "预算" in query or "budget" in query.lower():
        for keywords, value in _QUALITATIVE_BUDGETS:
            if any(keyword in query for keyword in keywords):
                return value

    return None

_TRAILING_PARTICLES = re.compile(r"(?:旅游|旅行|度假|游玩|亲子游|情侣游|家庭游|自由行|转转|看看|走走|玩玩|玩|游|了|吧|呢|啊|的|呀|哦|哈|嘛|吗)+$")
_DESTINATION_NOISE_HINTS = ("规划", "安排", "帮我", "帮忙", "制定", "预算", "budget")
_DESTINATION_SUFFIX_NOISE = ("亲子", "情侣", "家庭", "朋友")


def extract_destination(query: str, config: DraftConfig = DRAFT_CONFIG) -> str | None:
    for pattern in config.destination_patterns:
        match = pattern.search(query)
        if match:
            raw = match.group(1)
            cleaned = _TRAILING_PARTICLES.sub("", raw).strip()
            for suffix in _DESTINATION_SUFFIX_NOISE:
                cleaned = re.sub(rf"{suffix}$", "", cleaned).strip()
            if not cleaned or any(hint in cleaned for hint in _DESTINATION_NOISE_HINTS):
                continue
            return cleaned
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
