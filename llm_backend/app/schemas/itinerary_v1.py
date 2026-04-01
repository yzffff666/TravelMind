from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# 这是用来定义行程的必填字段。
P0_FIELDS = [
    "schema_version",
    "itinerary_id",
    "revision_id",
    "trip_profile.destination_city",
    "budget_summary.total_estimate",
]

# 这是用来定义行程的约束。
P0_CONSTRAINTS = {
    "days_min": 1,
    "slots_min_per_day": 1,
    "day_index_unique": True,
}

# 这是用来定义行程的推荐字段。
P1_FIELDS = [
    "days.risk",
    "days.cost_breakdown",
    "evidence.provider",
    "evidence.url",
    "evidence.fetched_at",
]

# 这是用来定义行程的假设文本。
P1_MISSING_ASSUMPTIONS = {
    "days.risk": "Risk details are incomplete; risk level may be underestimated.",
    "days.cost_breakdown": "Cost breakdown is partial; total estimate has uncertainty.",
    "evidence.provider": "Evidence provider is missing; source reliability cannot be fully graded.",
    "evidence.url": "Evidence URL is missing; traceability is reduced.",
    "evidence.fetched_at": "Evidence recency is unknown; freshness risk should be disclosed.",
}

# 这是用来定义行程的可选字段。
P2_FIELDS = [
    "days.alternatives",
    "days.theme",
    "budget_summary.uncertainty_note",
    "change_summary",
]

# 这是用来定义行程的字段降级策略。
FIELD_DEGRADE_STRATEGY = {
    "P0": "Missing P0 must not produce final_itinerary; return final_text for clarification.",
    "P1": "Missing P1 allows output but should append validation.assumptions and risk note.",
    "P2": "Missing P2 does not block output and should keep defaults/empty values.",
}

# 这是用来定义行程的版本规则。
REVISION_RULES = {
    "initial_revision": "First generated itinerary should set base_revision_id = null.",
    "derived_revision": "Edited itinerary should set base_revision_id to a previous revision_id.",
    "self_reference_forbidden": "base_revision_id must not equal revision_id.",
    "note": "M1 enforces only the safe local rule (self reference forbidden). Full lineage checks are handled in service/database layers.",
}

# 这是用来定义行程的向后兼容别名。
P0_REQUIRED_FIELDS = P0_FIELDS
P1_RECOMMENDED_FIELDS = P1_FIELDS
P2_OPTIONAL_FIELDS = P2_FIELDS


# 这是用来定义行程的约束。
class TripConstraints(BaseModel):
    budget_range: Optional[str] = None
    traveler_type: Optional[str] = None
    preferences: List[str] = Field(default_factory=list)


# 这是用来定义行程的行程配置。
class TripProfile(BaseModel):
    destination_city: str = Field(..., min_length=1)
    # 这是用来定义行程的日期范围。
    date_range: Optional[str] = None
    # 这是用来定义行程的旅行者。
    travelers: Optional[str] = None
    # 这是用来定义行程的约束。
    constraints: TripConstraints = Field(default_factory=TripConstraints)


# 这是用来定义行程的预算 breakdown。
class CostBreakdown(BaseModel):
    transport: Optional[float] = None
    hotel: Optional[float] = None
    tickets: Optional[float] = None
    food: Optional[float] = None
    other: Optional[float] = None


# 这是用来定义行程的风险。
class RiskItem(BaseModel):
    level: Optional[Literal["low", "medium", "high"]] = None
    text: Optional[str] = None


# 这是用来定义行程的备选方案。
class AlternativeItem(BaseModel):
    title: str = Field(..., min_length=1)
    reason: Optional[str] = None


# 这是用来定义行程的时段。
class ItinerarySlot(BaseModel):
    slot: str = Field(..., min_length=1)
    activity: str = Field(..., min_length=1)
    # M1 keeps these as free-text to minimize migration risk.
    place: Optional[str] = None
    transit: Optional[str] = None
    cost_breakdown: Optional[CostBreakdown] = None
    risk: Optional[RiskItem] = None
    alternatives: List[AlternativeItem] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)


# 这是用来定义行程的天。
class ItineraryDay(BaseModel):
    day_index: int = Field(..., ge=1)
    date: Optional[str] = None
    theme: Optional[str] = None
    slots: List[ItinerarySlot] = Field(..., min_length=1)


# 这是用来定义行程的预算 breakdown。
class BudgetByCategory(BaseModel):
    transport: Optional[float] = None
    hotel: Optional[float] = None
    tickets: Optional[float] = None
    food: Optional[float] = None
    other: Optional[float] = None


# 这是用来定义行程的预算 summary。
class BudgetSummary(BaseModel):
    total_estimate: float = Field(..., ge=0)
    uncertainty_note: Optional[str] = None
    by_category: BudgetByCategory = Field(default_factory=BudgetByCategory)


# 这是用来定义行程的证据。
class EvidenceItem(BaseModel):
    evidence_id: str = Field(..., min_length=1)
    provider: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None
    fetched_at: Optional[str] = None
    attribution: Optional[str] = None


# 这是用来定义行程的验证结果。
class ValidationResult(BaseModel):
    coverage_score: Optional[float] = None
    conflicts: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# 这是用来定义行程的变更 summary。
class ChangeSummary(BaseModel):
    changed_days: List[int] = Field(default_factory=list)
    diff_items: List[str] = Field(default_factory=list)


# 这是用来定义行程的最终结果。
class ItineraryV1(BaseModel):
    schema_version: str = Field(default="itinerary.v1")
    itinerary_id: str = Field(..., min_length=1)
    revision_id: str = Field(..., min_length=1)
    base_revision_id: Optional[str] = Field(default=None, min_length=1)
    trip_profile: TripProfile
    days: List[ItineraryDay] = Field(..., min_length=1)
    budget_summary: BudgetSummary
    evidence: List[EvidenceItem] = Field(default_factory=list)
    validation: ValidationResult = Field(default_factory=ValidationResult)
    change_summary: Optional[ChangeSummary] = None

    # 这是用来验证行程的 schema_version。
    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != "itinerary.v1":
            raise ValueError("schema_version must be 'itinerary.v1'")
        return value

    # 这是用来验证行程的 day_index 是否唯一。
    @field_validator("days")
    @classmethod
    def validate_day_indexes_unique(cls, value: List[ItineraryDay]) -> List[ItineraryDay]:
        day_indexes = [day.day_index for day in value]
        if len(day_indexes) != len(set(day_indexes)):
            raise ValueError("day_index must be unique")
        return value

    # 这是用来验证行程的 revision_link 是否合法。
    @model_validator(mode="after")
    def validate_revision_link(self) -> "ItineraryV1":
        if self.base_revision_id is not None and self.base_revision_id == self.revision_id:
            raise ValueError("base_revision_id must not equal revision_id")
        return self

    # 这是用来定义行程的契约规则。
    @classmethod
    def contract_rules(cls) -> Dict[str, object]:
        return {
            "P0_FIELDS": P0_FIELDS,
            "P0_CONSTRAINTS": P0_CONSTRAINTS,
            "P1_FIELDS": P1_FIELDS,
            "P1_MISSING_ASSUMPTIONS": P1_MISSING_ASSUMPTIONS,
            "P2_FIELDS": P2_FIELDS,
            "DEGRADE_STRATEGY": FIELD_DEGRADE_STRATEGY,
            "REVISION_RULES": REVISION_RULES,
        }

