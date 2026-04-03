<template>
  <div class="page">
    <!-- Left Panel: Input + Trip Summary + Budget -->
    <aside class="left-panel">
      <div class="left-scroll">
        <nav class="nav">
          <button class="nav-back" @click="goHome">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </nav>

        <header class="brand">
          <h1 class="brand-name">TravelMind</h1>
          <p class="brand-sub">描述你的理想旅行，AI 为你打造专属行程规划</p>
        </header>

        <section class="input-section">
          <div class="textarea-wrap" :class="{ focused: isTextareaFocused, disabled: isStreaming }">
            <textarea
              ref="textareaRef"
              v-model="query"
              :disabled="isStreaming"
              rows="3"
              placeholder="上海 4 天，预算 6000，情侣出行，喜欢文化体验和地道美食…"
              @focus="isTextareaFocused = true"
              @blur="isTextareaFocused = false"
            />
          </div>
          <div class="input-actions">
            <button
              class="btn-plan"
              :disabled="isStreaming || !query.trim()"
              @click="submitQuery"
            >
              <svg v-if="isStreaming" class="spinner" width="16" height="16" viewBox="0 0 16 16" fill="none">
                <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="32" stroke-dashoffset="10" stroke-linecap="round"/>
              </svg>
              {{ isStreaming ? '规划中…' : '开始规划' }}
            </button>
            <button
              v-if="canReset"
              class="btn-reset"
              :disabled="isStreaming"
              @click="resetPlanner"
            >
              重置
            </button>
          </div>
        </section>

        <!-- Status messages -->
        <section v-if="phase !== 'idle'" class="status-section">
          <div class="status-badge" :class="'st-' + phase">
            <span class="status-dot" :class="{ pulse: phase === 'planning' || phase === 'editing' }" />
            {{ statusText }}
          </div>
          <p v-if="clarificationMessage" class="status-msg warn">{{ clarificationMessage }}</p>
          <p v-if="errorText" class="status-msg error">{{ errorText }}</p>
          <p v-if="finalText" class="status-msg">{{ finalText }}</p>
          <p v-if="explanation" class="status-msg muted">{{ explanation }}</p>
        </section>

        <!-- Edit Diff Summary -->
        <section v-if="editDiff" class="edit-diff-card fade-in">
          <div class="diff-header">
            <svg class="diff-icon" width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span class="diff-title">行程已修改</span>
          </div>
          <ul v-if="editDiff.summary.diff_items.length" class="diff-list">
            <li
              v-for="(item, i) in editDiff.summary.diff_items"
              :key="i"
              class="diff-item"
            >{{ item }}</li>
          </ul>
          <div v-if="editDiff.summary.changed_days.length" class="diff-days">
            <span class="diff-days-label">涉及天数：</span>
            <span
              v-for="d in editDiff.summary.changed_days"
              :key="d"
              class="diff-day-tag"
            >第 {{ d }} 天</span>
          </div>
          <p v-if="editDiff.explanation" class="diff-explanation">{{ editDiff.explanation }}</p>
        </section>

        <!-- Trip Overview (visible after itinerary generated) -->
        <section v-if="itinerary" class="trip-overview fade-in">
          <div class="ov-header">
            <svg class="ov-icon" width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" stroke="currentColor" stroke-width="1.5"/>
              <circle cx="12" cy="9" r="2.5" stroke="currentColor" stroke-width="1.5"/>
            </svg>
            <h3 class="ov-city">{{ itinerary.trip_profile.destination_city }}</h3>
          </div>
          <div class="ov-tags">
            <span
              v-if="itinerary.trip_profile.constraints?.traveler_type"
              class="tag tag-accent"
            >{{ itinerary.trip_profile.constraints.traveler_type }}</span>
            <span class="tag">{{ itinerary.days.length }} 天</span>
            <span
              v-if="itinerary.trip_profile.constraints?.budget_range"
              class="tag"
            >{{ itinerary.trip_profile.constraints.budget_range }}</span>
            <span
              v-for="pref in (itinerary.trip_profile.constraints?.preferences || [])"
              :key="pref"
              class="tag tag-warm"
            >{{ pref }}</span>
          </div>
        </section>

        <!-- Budget Breakdown -->
        <section v-if="itinerary?.budget_summary" class="budget-card fade-in">
          <div class="bgt-header">
            <span class="bgt-label">预算概览</span>
            <span class="bgt-total">&yen;{{ formatNumber(itinerary.budget_summary.total_estimate) }}</span>
          </div>
          <div v-if="budgetCategories.length" class="bgt-bars">
            <div
              v-for="(cat, ci) in budgetCategories"
              :key="cat.label"
              class="bgt-row"
              :style="{ animationDelay: `${ci * 0.08 + 0.15}s` }"
            >
              <div class="bgt-row-top">
                <span class="bgt-dot" :style="{ background: cat.color }" />
                <span class="bgt-cat">{{ cat.label }}</span>
                <span class="bgt-amt">&yen;{{ formatNumber(cat.value) }}</span>
              </div>
              <div class="bgt-track">
                <div
                  class="bgt-fill"
                  :style="{ '--target-width': cat.percent + '%', background: cat.color }"
                />
              </div>
            </div>
          </div>
          <p v-if="itinerary.budget_summary.uncertainty_note" class="bgt-note">
            {{ itinerary.budget_summary.uncertainty_note }}
          </p>
        </section>

        <!-- Validation assumptions -->
        <section v-if="itinerary?.validation?.assumptions?.length" class="assumptions fade-in">
          <p
            v-for="(note, i) in itinerary.validation.assumptions"
            :key="i"
            class="asm-item"
          >{{ note }}</p>
        </section>
      </div>
    </aside>

    <!-- Right Panel: Itinerary Timeline -->
    <main class="right-panel" ref="scrollRef">
      <!-- Empty state -->
      <div v-if="!itinerary && phase === 'idle'" class="empty">
        <div class="empty-visual">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
            <circle cx="32" cy="28" r="18" stroke="currentColor" stroke-width="1.2" opacity="0.25"/>
            <path d="M32 10v36M14 28h36" stroke="currentColor" stroke-width="1" opacity="0.12"/>
            <path d="M32 16c-5.52 0-10 4.48-10 10 0 8 10 18 10 18s10-10 10-18c0-5.52-4.48-10-10-10z" stroke="currentColor" stroke-width="1.5"/>
            <circle cx="32" cy="26" r="3" stroke="currentColor" stroke-width="1.5"/>
            <path d="M20 52h24M24 48h16" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" opacity="0.2"/>
          </svg>
        </div>
        <p class="empty-title">你的行程将在这里呈现</p>
        <p class="empty-sub">在左侧输入旅行需求，AI 将为你生成详细行程</p>
      </div>

      <!-- Loading state -->
      <div v-if="!itinerary && phase === 'planning'" class="loading-state">
        <div class="ld-ring" />
        <p class="ld-text">正在为你规划行程…</p>
      </div>

      <!-- Itinerary timeline -->
      <div v-if="itinerary" ref="resultRef" class="itinerary">
        <div
          v-for="(day, dayIdx) in itinerary.days"
          :key="day.day_index"
          class="day-section slide-up"
          :style="{ animationDelay: `${dayIdx * 0.12}s` }"
        >
          <!-- Day header -->
          <div class="day-hdr">
            <span class="day-num">第 {{ day.day_index }} 天</span>
            <span v-if="day.theme" class="day-theme">{{ day.theme }}</span>
          </div>

          <!-- Slots timeline -->
          <div class="timeline">
            <div
              v-for="(slot, si) in day.slots"
              :key="`${day.day_index}-${si}`"
              class="tl-item slide-up"
              :style="{ animationDelay: `${dayIdx * 0.12 + si * 0.06 + 0.08}s` }"
            >
              <!-- Connector (dot + line) -->
              <div class="tl-rail">
                <span class="tl-dot" />
                <span v-if="si < day.slots.length - 1" class="tl-line" />
              </div>

              <!-- Place card -->
              <div class="pc">
                <span class="pc-slot">{{ slot.slot }}</span>
                <h4 class="pc-activity">{{ slot.activity }}</h4>

                <div v-if="slot.place" class="pc-row">
                  <svg class="pc-ico" width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" stroke="currentColor" stroke-width="1.5"/>
                    <circle cx="12" cy="9" r="2" stroke="currentColor" stroke-width="1.5"/>
                  </svg>
                  <span>{{ slot.place }}</span>
                </div>

                <div v-if="slot.transit" class="pc-row pc-transit">
                  <svg class="pc-ico" width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M13 17l5-5-5-5M6 17l5-5-5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  <span>{{ slot.transit }}</span>
                </div>

                <span v-if="getSlotCost(slot)" class="pc-cost">
                  &yen;{{ formatNumber(getSlotCost(slot)!) }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiService } from '../services/api'

// ---------- ItineraryV1 interfaces ----------

interface CostBreakdown {
  transport?: number | null
  hotel?: number | null
  tickets?: number | null
  food?: number | null
  other?: number | null
}

interface RiskItem {
  level?: 'low' | 'medium' | 'high' | null
  text?: string | null
}

interface AlternativeItem {
  title: string
  reason?: string | null
}

interface ItinerarySlot {
  slot: string
  activity: string
  place?: string | null
  transit?: string | null
  cost_breakdown?: CostBreakdown | null
  risk?: RiskItem | null
  alternatives?: AlternativeItem[]
  evidence_refs?: string[]
}

interface ItineraryDay {
  day_index: number
  date?: string | null
  theme?: string | null
  slots: ItinerarySlot[]
}

interface TripConstraints {
  budget_range?: string | null
  traveler_type?: string | null
  preferences?: string[]
}

interface TripProfile {
  destination_city: string
  date_range?: string | null
  travelers?: string | null
  constraints?: TripConstraints
}

interface BudgetByCategory {
  transport?: number | null
  hotel?: number | null
  tickets?: number | null
  food?: number | null
  other?: number | null
}

interface BudgetSummary {
  total_estimate: number
  uncertainty_note?: string | null
  by_category?: BudgetByCategory
}

interface ValidationResult {
  coverage_score?: number | null
  conflicts?: string[]
  assumptions?: string[]
}

interface ItineraryResult {
  schema_version?: string
  itinerary_id?: string
  revision_id?: string
  trip_profile: TripProfile
  days: ItineraryDay[]
  budget_summary: BudgetSummary
  evidence?: unknown[]
  validation?: ValidationResult
}

interface ChangeSummary {
  changed_days: number[]
  diff_items: string[]
}

type PlannerPhase = 'idle' | 'clarifying' | 'planning' | 'editing' | 'done' | 'error'

// ---------- State ----------

const router = useRouter()
const query = ref('')
const conversationId = ref<string | null>(null)
const phase = ref<PlannerPhase>('idle')
const clarificationMessage = ref('')
const finalText = ref('')
const explanation = ref('')
const errorText = ref('')
const itinerary = ref<ItineraryResult | null>(null)
const isStreaming = ref(false)
const isTextareaFocused = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const resultRef = ref<HTMLElement | null>(null)
const scrollRef = ref<HTMLElement | null>(null)
const currentIntent = ref('')
const editDiff = ref<{ summary: ChangeSummary; explanation: string } | null>(null)

// ---------- Computed ----------

const intentLabel = computed(() => {
  const map: Record<string, string> = {
    create: '生成行程',
    edit: '编辑行程',
    qa: '行程问答',
    reset: '重置会话',
  }
  return map[currentIntent.value] || ''
})

const statusText = computed(() => {
  const intentSuffix = intentLabel.value ? `（${intentLabel.value}）` : ''
  switch (phase.value) {
    case 'planning': return `正在生成草案${intentSuffix}`
    case 'editing': return `正在编辑行程${intentSuffix}`
    case 'clarifying': return '需要补充信息'
    case 'done': return itinerary.value ? `草案已生成${intentSuffix}` : `已完成${intentSuffix}`
    case 'error': return '请求失败'
    default: return '等待输入'
  }
})

const canReset = computed(() =>
  phase.value !== 'idle' ||
  Boolean(query.value.trim()) ||
  Boolean(itinerary.value) ||
  Boolean(finalText.value) ||
  Boolean(clarificationMessage.value) ||
  Boolean(errorText.value) ||
  Boolean(explanation.value)
)

const budgetCategories = computed(() => {
  const cat = itinerary.value?.budget_summary?.by_category
  if (!cat) return []
  const total = itinerary.value!.budget_summary.total_estimate || 1
  const mapping: [string, number | null | undefined, string][] = [
    ['交通', cat.transport, '#0ea5e9'],
    ['住宿', cat.hotel, '#a78bfa'],
    ['门票', cat.tickets, '#f59e0b'],
    ['餐饮', cat.food, '#22c55e'],
    ['其他', cat.other, '#64748b'],
  ]
  return mapping
    .filter(([, v]) => v && v > 0)
    .map(([label, value, color]) => ({
      label,
      value: value as number,
      color,
      percent: Math.round(((value as number) / total) * 100),
    }))
})

// ---------- Helpers ----------

const formatNumber = (n: number) => Math.round(n).toLocaleString('zh-CN')

const getSlotCost = (slot: ItinerarySlot): number | null => {
  const cb = slot.cost_breakdown
  if (!cb) return null
  const sum = (cb.transport || 0) + (cb.hotel || 0) + (cb.tickets || 0) + (cb.food || 0) + (cb.other || 0)
  return sum > 0 ? sum : null
}

// ---------- Actions ----------

const resetResultState = () => {
  clarificationMessage.value = ''
  finalText.value = ''
  explanation.value = ''
  errorText.value = ''
  itinerary.value = null
  currentIntent.value = ''
  editDiff.value = null
}

const resetPlanner = async () => {
  query.value = ''
  conversationId.value = null
  phase.value = 'idle'
  isStreaming.value = false
  resetResultState()
  await nextTick()
  textareaRef.value?.focus()
}

const goHome = () => router.push('/')

const scrollToResult = async () => {
  await nextTick()
  scrollRef.value?.scrollTo({ top: 0, behavior: 'smooth' })
}

const submitQuery = async () => {
  if (!query.value.trim()) return
  const userId = localStorage.getItem('user_id')
  if (!userId) {
    errorText.value = '缺少 user_id，请重新登录后重试。'
    phase.value = 'error'
    return
  }

  editDiff.value = null
  currentIntent.value = ''
  clarificationMessage.value = ''
  finalText.value = ''
  explanation.value = ''
  errorText.value = ''
  phase.value = 'planning'
  isStreaming.value = true

  try {
    const result = await ApiService.travelQueryStream(
      {
        query: query.value.trim(),
        userId,
        conversationId: conversationId.value || undefined,
      },
      {
        onIntentRouted: (envelope) => {
          currentIntent.value = envelope.payload.intent || ''
          if (envelope.payload.intent === 'edit') {
            phase.value = 'editing'
          }
        },
        onStageStart: () => {
          phase.value = 'clarifying'
        },
        onStageProgress: (envelope) => {
          phase.value = 'clarifying'
          clarificationMessage.value = envelope.payload.message || ''
        },
        onFinalItinerary: (envelope) => {
          phase.value = 'done'
          itinerary.value = envelope.payload.itinerary as ItineraryResult
          explanation.value = envelope.payload.explanation || ''
          scrollToResult()
        },
        onEditDiff: (envelope) => {
          editDiff.value = {
            summary: envelope.payload.change_summary,
            explanation: envelope.payload.explanation,
          }
        },
        onResetDone: (envelope) => {
          phase.value = 'done'
          itinerary.value = null
          finalText.value = envelope.payload.text || '会话已重置，可以开始新的行程规划。'
        },
        onFinalText: (envelope) => {
          phase.value = 'done'
          finalText.value = envelope.payload.text || ''
        },
        onError: (envelope) => {
          phase.value = 'error'
          errorText.value = envelope.payload.text || '行程生成失败，请稍后再试。'
        },
        onTextFallback: (text) => {
          if (!clarificationMessage.value && !finalText.value && !explanation.value) {
            finalText.value = text
          }
        },
      }
    )
    if (result.conversationId) {
      conversationId.value = result.conversationId
    }
  } catch (err) {
    phase.value = 'error'
    errorText.value = err instanceof Error ? err.message : '请求失败，请稍后再试。'
  } finally {
    isStreaming.value = false
  }
}
</script>

<!-- Global font import (unscoped) -->
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap');
</style>

<style scoped>
/* ==================== Design Tokens ==================== */
.page {
  --bg-deep: #08080d;
  --bg: #0e0e15;
  --bg-card: #141420;
  --bg-card-hover: #1a1a28;
  --border: #1c1c2a;
  --border-hover: #2c2c3e;

  --accent: #0ea5e9;
  --accent-soft: rgba(14, 165, 233, 0.12);
  --accent-warm: #f59e0b;
  --accent-warm-soft: rgba(245, 158, 11, 0.10);
  --success: #22c55e;
  --success-soft: rgba(34, 197, 94, 0.10);
  --warn: #f59e0b;
  --warn-soft: rgba(245, 158, 11, 0.10);
  --error: #ef4444;
  --error-soft: rgba(239, 68, 68, 0.10);

  --text: #e8e8f0;
  --text-sec: #8b8b9e;
  --text-muted: #50506a;

  --r-sm: 8px;
  --r-md: 12px;
  --r-lg: 16px;

  display: flex;
  height: 100vh;
  background: var(--bg-deep);
  color: var(--text);
  font-family: 'Inter', 'Noto Sans SC', system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
}

/* ==================== Left Panel ==================== */

.left-panel {
  width: 380px;
  flex-shrink: 0;
  background: var(--bg);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.left-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ---- Nav ---- */

.nav { display: flex; align-items: center; }

.nav-back {
  display: inline-flex;
  align-items: center;
  padding: 6px 8px;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}

.nav-back:hover {
  color: var(--text-sec);
  border-color: var(--border-hover);
}

/* ---- Brand ---- */

.brand { padding: 4px 0; }

.brand-name {
  margin: 0;
  font-size: 28px;
  font-weight: 300;
  letter-spacing: -0.03em;
  background: linear-gradient(135deg, #e0f2fe 0%, #0ea5e9 55%, #0284c7 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.brand-sub {
  margin: 8px 0 0;
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.55;
  font-weight: 300;
}

/* ---- Input ---- */

.input-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.textarea-wrap {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--bg-deep);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.textarea-wrap.focused {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.textarea-wrap.disabled { opacity: 0.5; }

textarea {
  display: block;
  width: 100%;
  border: none;
  background: transparent;
  color: var(--text);
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.6;
  resize: vertical;
  border-radius: var(--r-md);
  font-family: inherit;
}

textarea:focus { outline: none; }
textarea::placeholder { color: var(--text-muted); }

.input-actions {
  display: flex;
  gap: 8px;
}

.btn-plan {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  color: #fff;
  background: var(--accent);
  border: none;
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.btn-plan:hover:not(:disabled) {
  background: #0284c7;
  box-shadow: 0 4px 20px rgba(14, 165, 233, 0.28);
}

.btn-plan:active:not(:disabled) { transform: scale(0.98); }
.btn-plan:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-reset {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.btn-reset:hover:not(:disabled) {
  color: var(--text-sec);
  border-color: var(--border-hover);
}

.btn-reset:disabled { opacity: 0.4; cursor: not-allowed; }

.spinner { animation: spin 0.8s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

/* ---- Status ---- */

.status-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 500;
  padding: 4px 12px;
  border-radius: 999px;
  width: fit-content;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.st-planning  { background: var(--accent-soft); color: #7dd3fc; }
.st-planning .status-dot  { background: var(--accent); }
.st-clarifying { background: var(--warn-soft); color: #fde68a; }
.st-clarifying .status-dot { background: var(--warn); }
.st-editing { background: rgba(167, 139, 250, 0.12); color: #c4b5fd; }
.st-editing .status-dot { background: #a78bfa; }
.st-done { background: var(--success-soft); color: #bbf7d0; }
.st-done .status-dot { background: var(--success); }
.st-error { background: var(--error-soft); color: #fecaca; }
.st-error .status-dot { background: var(--error); }
.st-idle { background: rgba(255,255,255,0.04); color: var(--text-muted); }
.st-idle .status-dot { background: var(--text-muted); }

.pulse { animation: pulse-ring 1.2s ease-in-out infinite; }

@keyframes pulse-ring {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.status-msg {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
}

.status-msg.warn  { color: #fde68a; }
.status-msg.error { color: #fca5a5; }
.status-msg.muted { color: var(--text-sec); }

/* ---- Trip Overview ---- */

.trip-overview {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 18px;
}

.ov-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.ov-icon { color: var(--accent); flex-shrink: 0; }

.ov-city {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.ov-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  display: inline-flex;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 500;
  border-radius: 999px;
  background: rgba(255,255,255,0.05);
  color: var(--text-sec);
  border: 1px solid var(--border);
}

.tag-accent {
  background: var(--accent-soft);
  color: #7dd3fc;
  border-color: rgba(14, 165, 233, 0.2);
}

.tag-warm {
  background: var(--accent-warm-soft);
  color: #fde68a;
  border-color: rgba(245, 158, 11, 0.2);
}

/* ---- Budget Card ---- */

.budget-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 18px;
}

.bgt-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 16px;
}

.bgt-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.bgt-total {
  font-size: 24px;
  font-weight: 600;
  color: var(--accent-warm);
  letter-spacing: -0.02em;
}

.bgt-bars {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.bgt-row {
  animation: fadeIn 0.4s ease-out both;
}

.bgt-row-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.bgt-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}

.bgt-cat {
  font-size: 12px;
  color: var(--text-sec);
}

.bgt-amt {
  margin-left: auto;
  font-size: 12px;
  font-weight: 500;
  color: var(--text);
}

.bgt-track {
  height: 4px;
  background: rgba(255,255,255,0.04);
  border-radius: 2px;
  overflow: hidden;
}

.bgt-fill {
  height: 100%;
  border-radius: 2px;
  width: var(--target-width);
  transform-origin: left;
  animation: barScale 0.8s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes barScale {
  from { transform: scaleX(0); }
  to   { transform: scaleX(1); }
}

.bgt-note {
  margin: 14px 0 0;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}

/* ---- Assumptions ---- */

.assumptions { padding: 0; }

.asm-item {
  margin: 0 0 4px;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
  padding-left: 12px;
  position: relative;
}

.asm-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 7px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--text-muted);
}

/* ==================== Right Panel ==================== */

.right-panel {
  flex: 1;
  overflow-y: auto;
  padding: 48px 48px 48px 56px;
  scroll-behavior: smooth;
}

/* ---- Empty state ---- */

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: 40px;
}

.empty-visual {
  color: var(--text-muted);
  opacity: 0.35;
  margin-bottom: 24px;
}

.empty-title {
  margin: 0;
  font-size: 16px;
  font-weight: 400;
  color: var(--text-sec);
  letter-spacing: -0.01em;
}

.empty-sub {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--text-muted);
  max-width: 280px;
}

/* ---- Loading state ---- */

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 20px;
}

.ld-ring {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  animation: spin 1s linear infinite;
}

.ld-text {
  margin: 0;
  font-size: 14px;
  color: var(--text-sec);
  font-weight: 400;
}

/* ---- Itinerary ---- */

.itinerary { max-width: 680px; }

.day-section { margin-bottom: 44px; }
.day-section:last-child { margin-bottom: 0; }

.day-hdr {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 22px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.day-num {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  padding: 4px 14px;
  background: var(--accent-soft);
  border-radius: 999px;
  letter-spacing: 0.03em;
}

.day-theme {
  font-size: 14px;
  font-weight: 400;
  color: var(--text-sec);
  font-style: italic;
}

/* Timeline */

.timeline {
  position: relative;
  padding-left: 32px;
}

.tl-item {
  position: relative;
  padding-bottom: 22px;
}

.tl-item:last-child { padding-bottom: 0; }

.tl-rail {
  position: absolute;
  left: -32px;
  top: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  width: 12px;
}

.tl-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--bg-deep);
  border: 2px solid var(--accent);
  flex-shrink: 0;
  z-index: 1;
  margin-top: 8px;
}

.tl-line {
  width: 1px;
  flex: 1;
  background: var(--border);
  margin-top: 4px;
}

/* Place Card */

.pc {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 16px 20px;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
}

.pc:hover {
  border-color: var(--border-hover);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
  transform: translateY(-2px);
}

.pc-slot {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 6px;
}

.pc-activity {
  margin: 0 0 10px;
  font-size: 15px;
  font-weight: 500;
  line-height: 1.45;
  color: var(--text);
}

.pc-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 12.5px;
  color: var(--text-sec);
  line-height: 1.5;
}

.pc-row:last-of-type { margin-bottom: 0; }

.pc-ico {
  flex-shrink: 0;
  margin-top: 1px;
  color: var(--text-muted);
}

.pc-transit {
  color: var(--text-muted);
  font-size: 11.5px;
}

.pc-cost {
  display: inline-flex;
  margin-top: 10px;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 500;
  color: var(--accent-warm);
  background: var(--accent-warm-soft);
  border-radius: var(--r-sm);
  letter-spacing: 0.01em;
}

/* ---- Edit Diff Card ---- */

.edit-diff-card {
  background: var(--bg-card);
  border: 1px solid rgba(167, 139, 250, 0.2);
  border-radius: var(--r-lg);
  padding: 16px 18px;
}

.diff-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.diff-icon { color: #a78bfa; flex-shrink: 0; }

.diff-title {
  font-size: 12px;
  font-weight: 600;
  color: #c4b5fd;
  letter-spacing: 0.02em;
}

.diff-list {
  margin: 0 0 10px;
  padding: 0 0 0 18px;
  list-style: none;
}

.diff-item {
  position: relative;
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.7;
  padding-left: 2px;
}

.diff-item::before {
  content: '›';
  position: absolute;
  left: -14px;
  color: #a78bfa;
  font-weight: 600;
}

.diff-days {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.diff-days-label {
  font-size: 11px;
  color: var(--text-muted);
}

.diff-day-tag {
  display: inline-flex;
  padding: 2px 8px;
  font-size: 10.5px;
  font-weight: 500;
  color: #c4b5fd;
  background: rgba(167, 139, 250, 0.10);
  border-radius: 999px;
  border: 1px solid rgba(167, 139, 250, 0.18);
}

.diff-explanation {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--text-sec);
  line-height: 1.55;
}

/* ==================== Animations ==================== */

.fade-in { animation: fadeIn 0.4s ease-out both; }
.slide-up { animation: slideUp 0.5s ease-out both; }

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(18px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ==================== Responsive ==================== */

@media (max-width: 768px) {
  .page { flex-direction: column; }

  .left-panel {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid var(--border);
    max-height: 45vh;
  }

  .right-panel { padding: 28px 16px; }

  .itinerary { max-width: 100%; }

  .brand-name { font-size: 24px; }
}

@media (max-width: 480px) {
  .left-scroll { padding: 16px; gap: 16px; }

  .right-panel { padding: 20px 12px; }

  .timeline { padding-left: 24px; }
  .tl-rail  { left: -24px; }

  .pc { padding: 14px 16px; }

  .day-hdr { gap: 10px; margin-bottom: 16px; padding-bottom: 10px; }
}
</style>
