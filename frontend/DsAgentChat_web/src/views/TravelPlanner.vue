<template>
  <div class="page">
    <!-- Mobile Tab Bar -->
    <div v-if="isNarrow" class="tab-bar">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'chat' }"
        @click="activeTab = 'chat'"
      >对话</button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'itinerary' }"
        @click="activeTab = 'itinerary'"
      >行程</button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'map' }"
        @click="activeTab = 'map'"
      >地图</button>
    </div>

    <!-- ========== Chat Panel (Left) ========== -->
    <aside
      class="chat-panel"
      v-show="!isNarrow || activeTab === 'chat'"
    >
      <div class="chat-scroll" ref="chatScrollRef">
        <nav class="nav">
          <div class="brand-lockup">
            <h1 class="brand-name">TravelMind</h1>
            <StatusBadge :tone="workspaceStatusTone">{{ workspaceStatusLabel }}</StatusBadge>
          </div>
          <div class="nav-spacer" />
          <button class="user-menu-btn" aria-label="退出登录" @click="handleLogout" title="退出登录">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/>
              <polyline points="16 17 21 12 16 7"/>
              <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
          </button>
        </nav>

        <!-- Chat Messages -->
        <div class="chat-messages">
          <div v-if="!chatHistory.length && phase === 'idle'" class="welcome">
            <div class="welcome-card">
              <span class="welcome-kicker">AI Travel Concierge</span>
              <h2 class="welcome-title">把下一段旅程，写成一份可以出发的计划。</h2>
              <p class="welcome-sub">告诉我目的地、天数、预算和旅行节奏，我会把对话整理成行程、证据和地图点位。</p>
              <div class="welcome-prompts" aria-label="推荐旅行需求">
                <button
                  v-for="prompt in welcomePrompts"
                  :key="prompt"
                  class="welcome-prompt"
                  type="button"
                  @click="submitQuery(prompt)"
                >
                  {{ prompt }}
                </button>
              </div>
            </div>
          </div>

          <template v-for="msg in chatHistory" :key="msg.id">
            <!-- User bubble -->
            <div v-if="msg.role === 'user'" class="msg msg-user slide-up">
              <p class="msg-text">{{ msg.text }}</p>
            </div>
            <!-- Assistant bubble -->
            <div v-else class="msg msg-assistant slide-up">
              <DiffCard v-if="msg.type === 'diff' && msg.diffData" :diff="msg.diffData" />
              <p v-else class="msg-text" :class="{ 'msg-warn': msg.type === 'clarification', 'msg-error': msg.type === 'error' }">
                {{ cleanMsg(msg.text) }}
              </p>
            </div>
          </template>

          <!-- Live phase indicator -->
          <PhaseIndicator
            :phase="phase"
            :intentLabel="intentLabel"
          />

          <!-- Live clarification (before it becomes a chat entry) -->
          <p v-if="liveClarification" class="msg msg-assistant slide-up">
            <span class="msg-text msg-warn">{{ liveClarification }}</span>
          </p>
        </div>
      </div>
    </aside>

    <!-- ========== Itinerary Panel (Right) ========== -->
    <main
      class="itinerary-panel"
      v-show="!isNarrow || activeTab === 'itinerary'"
      ref="itineraryScrollRef"
    >
      <!-- Empty state -->
      <EmptyState v-if="!itinerary && phase === 'idle'" @suggest="submitQuery" />

      <!-- Error state with retry -->
      <ErrorState
        v-else-if="phase === 'error' && !itinerary"
        :errorText="errorText"
        @retry="retryLast"
        @reset="resetPlanner"
      />

      <!-- Loading state with progressive rendering -->
      <div v-else-if="!itinerary && (phase === 'planning' || phase === 'editing')" class="loading-state">
        <template v-if="partialDays.length > 0">
          <p v-if="pipelineStatus" class="pipeline-status fade-in">{{ pipelineStatus }}</p>
          <div class="itinerary-content">
            <ItineraryTimeline
              :days="partialDays"
              :changedDays="[]"
            />
            <div class="ld-ring-inline" />
          </div>
        </template>
        <template v-else>
          <div class="ld-ring" />
          <p class="ld-text">{{ pipelineStatus || '正在为你规划行程…' }}</p>
        </template>
      </div>

      <!-- Itinerary content -->
      <div v-if="itinerary" class="itinerary-content">
        <TripOverview
          :profile="itinerary.trip_profile"
          :dayCount="itinerary.days.length"
        />
        <ItineraryTimeline
          ref="timelineRef"
          :days="itinerary.days"
          :changedDays="changedDays"
        />
        <BudgetCard
          v-if="itinerary.budget_summary"
          :budget="itinerary.budget_summary"
        />

        <!-- Coverage score -->
        <div
          v-if="itinerary.validation?.coverage_score != null"
          class="coverage-bar fade-in"
        >
          <span class="coverage-label">数据覆盖率</span>
          <div class="coverage-track">
            <div
              class="coverage-fill"
              :style="{ width: `${Math.round((itinerary.validation!.coverage_score!) * 100)}%` }"
            />
          </div>
          <span class="coverage-pct">{{ Math.round((itinerary.validation!.coverage_score!) * 100) }}%</span>
        </div>

        <section v-if="itinerary.validation?.assumptions?.length" class="assumptions fade-in">
          <p
            v-for="(note, i) in itinerary.validation!.assumptions"
            :key="i"
            class="asm-item"
          >{{ note }}</p>
        </section>
      </div>
    </main>

    <!-- ========== Map Panel (Right on desktop, tab on mobile) ========== -->
    <section
      class="map-section"
      v-show="showMap"
    >
      <MapPanel
        ref="mapPanelRef"
        :days="mapDays"
        :activeDayIndex="activeDayIndex"
        :activeSlotIndex="activeSlotIndex"
        :visible="showMap"
        @selectDay="onMapSelectDay"
        @selectSlot="onMapSelectSlot"
      />
    </section>

    <!-- ========== Input Bar (Bottom, always visible) ========== -->
    <InputBar
      ref="inputBarRef"
      :isStreaming="isStreaming"
      :canReset="canReset"
      @submit="submitQuery"
      @reset="resetPlanner"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiService } from '../services/api'
import type { ItineraryResult, ItineraryDay, PlannerPhase, EditDiffData, ChatEntry } from '../types/itinerary'

import InputBar from '../components/chat/InputBar.vue'
import PhaseIndicator from '../components/chat/PhaseIndicator.vue'
import DiffCard from '../components/chat/DiffCard.vue'
import EmptyState from '../components/itinerary/EmptyState.vue'
import ErrorState from '../components/itinerary/ErrorState.vue'
import TripOverview from '../components/itinerary/TripOverview.vue'
import BudgetCard from '../components/itinerary/BudgetCard.vue'
import ItineraryTimeline from '../components/itinerary/ItineraryTimeline.vue'
import MapPanel from '../components/itinerary/MapPanel.vue'
import { StatusBadge } from '../components/ui'

// ---------- State ----------

const router = useRouter()
const conversationId = ref<string | null>(null)
const phase = ref<PlannerPhase>('idle')
const liveClarification = ref('')
const errorText = ref('')
const itinerary = ref<ItineraryResult | null>(null)
const partialDays = ref<ItineraryDay[]>([])
const pipelineStatus = ref('')
const isStreaming = ref(false)
const currentIntent = ref('')
const editDiff = ref<EditDiffData | null>(null)
const chatHistory = ref<ChatEntry[]>([])
const lastQuery = ref('')
const changedDays = ref<number[]>([])
let msgSeq = 0
let changedDaysTimer: ReturnType<typeof setTimeout> | null = null

const activeTab = ref<'chat' | 'itinerary' | 'map'>('chat')
const isNarrow = ref(false)
const chatScrollRef = ref<HTMLElement | null>(null)
const itineraryScrollRef = ref<HTMLElement | null>(null)
const inputBarRef = ref<InstanceType<typeof InputBar> | null>(null)
const timelineRef = ref<InstanceType<typeof ItineraryTimeline> | null>(null)
const activeDayIndex = ref(1)
const activeSlotIndex = ref<number | undefined>(undefined)

const mapDays = computed(() => itinerary.value?.days ?? partialDays.value)
const hasMapData = computed(() => mapDays.value.some(d =>
  d.slots.some(s => s.location != null)
))
const showMap = computed(() => {
  if (isNarrow.value) return activeTab.value === 'map'
  return (
    hasMapData.value ||
    itinerary.value != null ||
    phase.value === 'planning' ||
    phase.value === 'editing'
  )
})

function onMapSelectDay(dayIndex: number) {
  activeDayIndex.value = dayIndex
  activeSlotIndex.value = undefined
}

function onMapSelectSlot(_dayIndex: number, slotIndex: number) {
  activeSlotIndex.value = slotIndex
}

// ---------- Responsive ----------

const checkWidth = () => {
  isNarrow.value = window.innerWidth < 768
}

onMounted(() => {
  checkWidth()
  window.addEventListener('resize', checkWidth)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkWidth)
  if (changedDaysTimer) clearTimeout(changedDaysTimer)
})

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

const workspaceStatusLabel = computed(() => {
  if (isStreaming.value) return currentIntent.value === 'edit' ? '正在编辑' : '正在规划'
  if (phase.value === 'error') return '需要处理'
  if (itinerary.value) return '行程已就绪'
  return '准备规划'
})

const workspaceStatusTone = computed<'neutral' | 'info' | 'success' | 'warning' | 'danger'>(() => {
  if (phase.value === 'error') return 'danger'
  if (isStreaming.value) return 'info'
  if (itinerary.value) return 'success'
  return 'neutral'
})

const canReset = computed(() =>
  phase.value !== 'idle' ||
  Boolean(itinerary.value) ||
  chatHistory.value.length > 0
)
const welcomePrompts = [
  '帮我规划 3 天成都亲子游，预算中等，节奏轻松',
  '帮我规划 4 天普吉岛轻松游，偏好海岛和美食',
  '东京 5 天情侣旅行，想要城市漫步和好餐厅',
]

// ---------- Helpers ----------

const addChatEntry = (role: 'user' | 'assistant', text: string, type: ChatEntry['type'] = 'text', diffData?: EditDiffData) => {
  chatHistory.value.push({ id: ++msgSeq, role, text, type, diffData })
  scrollChatToBottom()
}

const scrollChatToBottom = async () => {
  await nextTick()
  if (chatScrollRef.value) {
    chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
  }
}

const scrollItineraryToTop = async () => {
  await nextTick()
  itineraryScrollRef.value?.scrollTo({ top: 0, behavior: 'smooth' })
}

const highlightChangedDays = (days: number[]) => {
  changedDays.value = days
  if (changedDaysTimer) clearTimeout(changedDaysTimer)
  changedDaysTimer = setTimeout(() => { changedDays.value = [] }, 4000)

  nextTick(() => {
    if (days.length > 0 && timelineRef.value) {
      timelineRef.value.scrollToDay(days[0])
    }
    if (isNarrow.value) {
      activeTab.value = 'itinerary'
    }
  })
}

// ---------- Actions ----------

const resetPlanner = async () => {
  conversationId.value = null
  phase.value = 'idle'
  isStreaming.value = false
  liveClarification.value = ''
  errorText.value = ''
  itinerary.value = null
  partialDays.value = []
  pipelineStatus.value = ''
  currentIntent.value = ''
  editDiff.value = null
  chatHistory.value = []
  lastQuery.value = ''
  changedDays.value = []
  if (changedDaysTimer) { clearTimeout(changedDaysTimer); changedDaysTimer = null }
  msgSeq = 0
  await nextTick()
  inputBarRef.value?.focus()
}

const cleanMsg = (text: string) =>
  text.replace(/（可选，不填也能先出草案）/g, '')

const handleLogout = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('user_id')
  router.push('/login')
}

const retryLast = () => {
  if (lastQuery.value) {
    errorText.value = ''
    phase.value = 'idle'
    submitQuery(lastQuery.value)
  }
}

const submitQuery = async (queryText: string) => {
  if (!queryText.trim()) return
  const userId = localStorage.getItem('user_id')
  if (!userId) {
    errorText.value = '缺少 user_id，请重新登录后重试。'
    phase.value = 'error'
    return
  }

  lastQuery.value = queryText
  addChatEntry('user', queryText)

  liveClarification.value = ''
  errorText.value = ''
  editDiff.value = null
  currentIntent.value = ''
  isStreaming.value = true

  if (isNarrow.value && itinerary.value) {
    activeTab.value = 'itinerary'
  }

  try {
    const result = await ApiService.travelQueryStream(
      {
        query: queryText.trim(),
        userId,
        conversationId: conversationId.value || undefined,
      },
      {
        onIntentRouted: (envelope) => {
          currentIntent.value = envelope.payload.intent || ''
          if (envelope.payload.intent === 'edit') {
            phase.value = 'editing'
          } else {
            phase.value = 'idle'
          }
        },
        onStageStart: (envelope) => {
          const stage = envelope.payload.stage
          if (stage === 'draft_plan') {
            phase.value = 'planning'
            partialDays.value = []
            pipelineStatus.value = ''
          } else {
            phase.value = 'clarifying'
          }
        },
        onPipelineComplete: (envelope) => {
          const count = envelope.payload.candidate_count ?? 0
          pipelineStatus.value = count > 0
            ? `找到 ${count} 个推荐地点，正在生成行程...`
            : '正在生成行程...'
        },
        onDayReady: (envelope) => {
          partialDays.value.push(envelope.payload.day as unknown as ItineraryDay)
        },
        onStageProgress: (envelope) => {
          const stage = envelope.payload.stage
          if (stage === 'validation_summary') {
            // validation progress during draft — stay in planning
          } else {
            phase.value = 'clarifying'
            liveClarification.value = envelope.payload.message || ''
          }
        },
        onToolResult: () => {
          // evidence batch received — keep planning phase
        },
        onFinalItinerary: (envelope) => {
          phase.value = 'done'
          itinerary.value = envelope.payload.itinerary as unknown as ItineraryResult
          partialDays.value = []
          pipelineStatus.value = ''
          activeDayIndex.value = 1
          activeSlotIndex.value = undefined
          const explanation = envelope.payload.explanation || ''
          if (explanation && !(currentIntent.value === 'edit' && editDiff.value)) {
            addChatEntry('assistant', explanation)
          }
          scrollItineraryToTop()
          if (isNarrow.value) {
            activeTab.value = 'itinerary'
          }
        },
        onEditDiff: (envelope) => {
          const diffData: EditDiffData = {
            summary: envelope.payload.change_summary,
            explanation: envelope.payload.explanation,
          }
          editDiff.value = diffData
          addChatEntry('assistant', '', 'diff', diffData)

          const days: number[] = diffData.summary?.changed_days ?? []
          if (days.length > 0) {
            highlightChangedDays(days)
          }
        },
        onResetDone: (envelope) => {
          phase.value = 'done'
          itinerary.value = null
          const text = envelope.payload.text || '会话已重置，可以开始新的行程规划。'
          addChatEntry('assistant', text)
        },
        onFinalText: (envelope) => {
          phase.value = 'done'
          const text = envelope.payload.text || ''
          if (text) {
            addChatEntry('assistant', text)
          }
        },
        onError: (envelope) => {
          phase.value = 'error'
          errorText.value = envelope.payload.text || '行程生成失败，请稍后再试。'
          addChatEntry('assistant', errorText.value, 'error')
        },
        onTextFallback: (text) => {
          if (text && phase.value !== 'done') {
            addChatEntry('assistant', text)
            phase.value = 'done'
          }
        },
      }
    )

    if (liveClarification.value) {
      addChatEntry('assistant', liveClarification.value, 'clarification')
      liveClarification.value = ''
    }

    if (result.conversationId) {
      conversationId.value = result.conversationId
    }
  } catch (err) {
    phase.value = 'error'
    errorText.value = err instanceof Error ? err.message : '请求失败，请稍后再试。'
    addChatEntry('assistant', errorText.value, 'error')
  } finally {
    isStreaming.value = false
    if (currentIntent.value === 'chat' || (currentIntent.value === 'create' && !itinerary.value)) {
      phase.value = 'idle'
    }
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
  --bg-deep: var(--tm-color-bg);
  --bg: var(--tm-color-surface);
  --bg-card: var(--tm-color-surface-elevated);
  --bg-card-hover: var(--tm-color-surface-solid);
  --border: var(--tm-color-border);
  --border-hover: var(--tm-color-border-strong);

  --accent: var(--tm-color-primary);
  --accent-soft: var(--tm-color-primary-soft);
  --accent-warm: var(--tm-color-warning);
  --accent-warm-soft: rgba(251, 191, 36, 0.12);
  --success: var(--tm-color-success);
  --success-soft: rgba(52, 211, 153, 0.12);
  --warn: var(--tm-color-warning);
  --warn-soft: rgba(251, 191, 36, 0.12);
  --error: var(--tm-color-danger);
  --error-soft: rgba(251, 113, 133, 0.12);

  --text: var(--tm-color-text-primary);
  --text-sec: var(--tm-color-text-secondary);
  --text-muted: var(--tm-color-text-muted);

  --r-sm: var(--tm-radius-md);
  --r-md: var(--tm-radius-lg);
  --r-lg: var(--tm-radius-2xl);

  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  padding: var(--tm-space-3);
  gap: var(--tm-space-3);
  background:
    radial-gradient(circle at 18% 12%, rgba(198, 161, 91, 0.18), transparent 32%),
    radial-gradient(circle at 82% 8%, rgba(245, 232, 198, 0.08), transparent 28%),
    var(--bg-deep);
  color: var(--text);
  font-family: var(--tm-font-sans);
  font-size: var(--tm-font-size-sm);
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
}

/* ==================== Tab Bar (mobile) ==================== */

.tab-bar {
  display: flex;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  border: 1px solid var(--border);
  border-radius: var(--tm-radius-xl);
  background: rgba(15, 23, 42, 0.78);
  backdrop-filter: var(--tm-blur-glass);
  overflow: hidden;
}

.tab-btn {
  flex: 1;
  padding: 12px 0;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn.active {
  color: var(--text);
  border-bottom-color: var(--tm-color-cyan);
  background: var(--tm-color-primary-soft);
}

.tab-btn:hover:not(.active) {
  color: var(--text-sec);
}

/* ==================== Dual Panel Layout ==================== */

.chat-panel,
.itinerary-panel {
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--tm-gradient-surface);
  box-shadow: var(--tm-shadow-card);
  backdrop-filter: var(--tm-blur-glass);
}

.map-section {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--tm-radius-2xl);
  background: var(--bg);
  box-shadow: var(--tm-shadow-card);
}

@media (min-width: 768px) {
  .page {
    display: grid;
    grid-template-columns: 2fr 3fr;
    grid-template-rows: 1fr auto;
    min-height: 0;
  }

  .chat-panel {
    grid-column: 1;
    grid-row: 1;
  }

  .itinerary-panel {
    grid-column: 2;
    grid-row: 1;
    display: flex;
    flex-direction: column;
  }

  .map-section {
    grid-column: 2;
    grid-row: 1;
    position: relative;
    z-index: 1;
  }

  /* When map is visible, itinerary panel shares the right column */
  .itinerary-panel + .map-section,
  .map-section {
    display: none;
  }

  .page:has(.map-section[style*="display: none"]) .itinerary-panel {
    grid-row: 1;
  }

  /* Three-area layout: chat | map+itinerary */
  .page:has(.map-section:not([style*="display: none"])) {
    grid-template-columns: 5fr 7fr;
    grid-template-rows: 2fr 3fr auto;
  }

  .page:has(.map-section:not([style*="display: none"])) .chat-panel {
    grid-column: 1;
    grid-row: 1 / 3;
  }

  .page:has(.map-section:not([style*="display: none"])) .map-section {
    display: block;
    grid-column: 2;
    grid-row: 1;
  }

  .page:has(.map-section:not([style*="display: none"])) .itinerary-panel {
    grid-column: 2;
    grid-row: 2;
  }

  .page > :deep(.input-bar) {
    grid-column: 1 / -1;
    grid-row: -1;
  }
}

@media (max-width: 767px) {
  .page {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .tab-bar { flex-shrink: 0; }

  .chat-panel,
  .itinerary-panel,
  .map-section {
    flex: 1 1 0;
    min-height: 0;
  }

  .chat-panel,
  .itinerary-panel {
    min-height: 320px;
  }

  .map-section {
    padding: 8px;
  }
}

/* ==================== Chat Panel ==================== */

.chat-panel {
  display: flex;
  flex-direction: column;
  border-radius: var(--tm-radius-2xl);
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
}

/* ---- Nav Header ---- */

.nav {
  display: flex;
  align-items: center;
  gap: var(--tm-space-3);
  padding: var(--tm-space-1) 0 var(--tm-space-6);
  flex-shrink: 0;
}

.nav-spacer { flex: 1; }

.brand-lockup {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--tm-space-3);
}

.brand-name {
  margin: 0;
  font-size: var(--tm-font-size-lg);
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--text);
}

.user-menu-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: rgba(15, 23, 42, 0.54);
  color: var(--text-sec);
  cursor: pointer;
  transition: all 0.2s;
}

.user-menu-btn:hover {
  color: var(--text);
  border-color: var(--border-hover);
  background: var(--tm-color-primary-soft);
}

.user-menu-btn:focus-visible {
  box-shadow: var(--tm-shadow-focus);
}

/* ---- Welcome State ---- */

.welcome {
  margin: auto 0;
  padding: var(--tm-space-4) 0 var(--tm-space-8);
  animation: fadeIn 0.6s ease-out both;
}

.welcome-card {
  position: relative;
  display: grid;
  gap: var(--tm-space-4);
  padding: var(--tm-space-6);
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-2xl);
  background:
    linear-gradient(145deg, rgba(24, 23, 20, 0.72), rgba(12, 12, 10, 0.52)),
    radial-gradient(circle at 90% 10%, rgba(198, 161, 91, 0.16), transparent 36%);
  box-shadow: var(--tm-shadow-card);
  overflow: hidden;
}

.welcome-card::before {
  content: '';
  position: absolute;
  inset: var(--tm-space-4);
  border: 1px solid rgba(217, 199, 160, 0.08);
  border-radius: calc(var(--tm-radius-2xl) - var(--tm-space-2));
  pointer-events: none;
}

.welcome-kicker {
  position: relative;
  color: var(--tm-color-primary);
  font-size: var(--tm-font-size-xs);
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.welcome-title {
  position: relative;
  max-width: 10em;
  margin: 0;
  font-size: clamp(32px, 5.4vw, 54px);
  font-weight: 800;
  color: var(--text);
  letter-spacing: -0.055em;
  line-height: 0.98;
}

.welcome-sub {
  position: relative;
  max-width: 34em;
  margin: 0;
  color: var(--text-sec);
  font-size: var(--tm-font-size-sm);
  font-weight: 400;
  line-height: var(--tm-line-height-normal);
}

.welcome-prompts {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  gap: var(--tm-space-2);
  margin-top: var(--tm-space-2);
}

.welcome-prompt {
  min-height: 34px;
  padding: 0 var(--tm-space-3);
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-pill);
  background: rgba(255, 255, 255, 0.03);
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-xs);
  font-weight: 700;
  transition:
    border-color var(--tm-motion-fast),
    background var(--tm-motion-fast),
    color var(--tm-motion-fast),
    transform var(--tm-motion-fast);
}

.welcome-prompt:hover {
  transform: translateY(-1px);
  border-color: var(--tm-color-border-strong);
  background: var(--tm-color-primary-soft);
  color: var(--tm-color-text-primary);
}

.welcome-prompt:focus-visible {
  box-shadow: var(--tm-shadow-focus);
}

/* ---- Chat Messages ---- */

.chat-messages {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.msg {
  max-width: 85%;
  animation: slideUp 0.3s ease-out both;
}

.msg-user {
  align-self: flex-end;
}

.msg-user .msg-text {
  background: var(--tm-gradient-brand);
  color: var(--text);
  border-radius: 20px 20px 4px 20px;
  padding: 12px 18px;
  font-size: 14px;
  line-height: 1.6;
}

.msg-assistant {
  align-self: flex-start;
}

.msg-assistant > .msg-text {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 4px 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-sec);
}

.msg-text {
  margin: 0;
  word-break: break-word;
  white-space: pre-wrap;
}

.msg-warn {
  color: #fde68a !important;
}

.msg-error {
  color: #fca5a5 !important;
}

/* ==================== Itinerary Panel ==================== */

.itinerary-panel {
  overflow-y: auto;
  padding: 40px 40px 40px 48px;
  scroll-behavior: smooth;
  border-radius: var(--tm-radius-2xl);
}

.itinerary-content {
  max-width: 700px;
  width: 100%;
  display: flex;
  flex-direction: column;
  min-height: min-content;
}

/* ---- Loading ---- */

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 24px;
}

.ld-ring {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.06);
  border-top-color: var(--text-sec);
  animation: spin 1s linear infinite;
}

.ld-text {
  margin: 0;
  font-size: 14px;
  color: var(--text-muted);
  font-weight: 400;
}

.ld-ring-inline {
  width: 24px;
  height: 24px;
  margin: 16px 0;
  border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.06);
  border-top-color: var(--text-sec);
  animation: spin 1s linear infinite;
}

.pipeline-status {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--text-sec);
  font-weight: 400;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* ---- Coverage Bar ---- */

.coverage-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 20px;
  padding: 12px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
}

.coverage-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-sec);
  white-space: nowrap;
}

.coverage-track {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: rgba(255,255,255,0.06);
  overflow: hidden;
}

.coverage-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--success);
  transition: width 0.6s ease-out;
}

.coverage-pct {
  font-size: 12px;
  font-weight: 600;
  color: var(--success);
  min-width: 32px;
  text-align: right;
}

/* ---- Assumptions ---- */

.assumptions { padding: 0; margin-top: 20px; }

.asm-item {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
  padding-left: 14px;
  position: relative;
}

.asm-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--text-muted);
}

/* ==================== Animations ==================== */

.fade-in { animation: fadeIn 0.4s ease-out both; }
.slide-up { animation: slideUp 0.3s ease-out both; }

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ==================== Responsive ==================== */

@media (max-width: 767px) {
  .itinerary-panel {
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    padding: 20px 16px;
  }
  .chat-scroll { padding: 20px 16px; }
  .brand-name { font-size: 16px; }
  .welcome-title { font-size: 22px; }
}
</style>
