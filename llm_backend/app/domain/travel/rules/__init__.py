"""
Travel 领域规则与配置集中目录。
- 所有可配置规则、正则、文案模板放在此处，与 domain 行为逻辑分离，便于维护与 i18n。
"""
from app.domain.travel.rules.clarification_rules import (
    CLARIFICATION_MSG_HARD_AND_SOFT,
    CLARIFICATION_MSG_HARD_ONLY,
    CLARIFICATION_STAGE_NAME,
    CONSTRAINT_PATTERNS,
    FIELD_LABELS,
    HARD_REQUIRED_FIELDS,
    SOFT_RECOMMENDED_FIELDS,
    SSE_EVENT_STAGE_PROGRESS,
    SSE_EVENT_STAGE_START,
)
from app.domain.travel.rules.api_rules import TRAVEL_API_RULES, TravelApiRules
from app.domain.travel.rules.draft_rules import DRAFT_CONFIG, DraftConfig
from app.domain.travel.rules.patch_rules import PATCH_RULES, PatchRules
from app.domain.travel.rules.qp_rules import QP_RULES, QPRules

__all__ = [
    "TRAVEL_API_RULES",
    "TravelApiRules",
    "CLARIFICATION_MSG_HARD_AND_SOFT",
    "CLARIFICATION_MSG_HARD_ONLY",
    "CLARIFICATION_STAGE_NAME",
    "CONSTRAINT_PATTERNS",
    "DRAFT_CONFIG",
    "DraftConfig",
    "FIELD_LABELS",
    "HARD_REQUIRED_FIELDS",
    "PATCH_RULES",
    "PatchRules",
    "QP_RULES",
    "QPRules",
    "SOFT_RECOMMENDED_FIELDS",
    "SSE_EVENT_STAGE_PROGRESS",
    "SSE_EVENT_STAGE_START",
]
