export interface CostBreakdown {
  transport?: number | null
  hotel?: number | null
  tickets?: number | null
  food?: number | null
  other?: number | null
}

export interface RiskItem {
  level?: 'low' | 'medium' | 'high' | null
  text?: string | null
}

export interface AlternativeItem {
  title: string
  reason?: string | null
}

export interface ItinerarySlot {
  slot: string
  activity: string
  place?: string | null
  transit?: string | null
  cost_breakdown?: CostBreakdown | null
  risk?: RiskItem | null
  alternatives?: AlternativeItem[]
  evidence_refs?: string[]
}

export interface ItineraryDay {
  day_index: number
  date?: string | null
  theme?: string | null
  slots: ItinerarySlot[]
}

export interface TripConstraints {
  budget_range?: string | null
  traveler_type?: string | null
  preferences?: string[]
}

export interface TripProfile {
  destination_city: string
  date_range?: string | null
  travelers?: string | null
  constraints?: TripConstraints
}

export interface BudgetByCategory {
  transport?: number | null
  hotel?: number | null
  tickets?: number | null
  food?: number | null
  other?: number | null
}

export interface BudgetSummary {
  total_estimate: number
  uncertainty_note?: string | null
  by_category?: BudgetByCategory
}

export interface ValidationResult {
  coverage_score?: number | null
  conflicts?: string[]
  assumptions?: string[]
}

export interface ItineraryResult {
  schema_version?: string
  itinerary_id?: string
  revision_id?: string
  trip_profile: TripProfile
  days: ItineraryDay[]
  budget_summary: BudgetSummary
  evidence?: unknown[]
  validation?: ValidationResult
}

export interface ChangeSummary {
  changed_days: number[]
  diff_items: string[]
}

export interface EditDiffData {
  summary: ChangeSummary
  explanation: string
}

export type PlannerPhase = 'idle' | 'clarifying' | 'planning' | 'editing' | 'done' | 'error'

export interface ChatEntry {
  id: number
  role: 'user' | 'assistant'
  text: string
  type: 'text' | 'clarification' | 'error' | 'diff'
  diffData?: EditDiffData
}
