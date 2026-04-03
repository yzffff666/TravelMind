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
    </div>

    <!-- ========== Chat Panel (Left) ========== -->
    <aside
      class="chat-panel"
      v-show="!isNarrow || activeTab === 'chat'"
    >
      <div class="chat-scroll" ref="chatScrollRef">
        <nav class="nav">
          <button class="nav-back" @click="goHome">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
          <h1 class="brand-name">TravelMind</h1>
        </nav>

        <!-- Chat Messages -->
        <div class="chat-messages">
          <p v-if="!chatHistory.length && phase === 'idle'" class="chat-hint">
            描述你的理想旅行，AI 为你打造专属行程规划
          </p>

          <template v-for="msg in chatHistory" :key="msg.id">
            <!-- User bubble -->
            <div v-if="msg.role === 'user'" class="msg msg-user slide-up">
              <p class="msg-text">{{ msg.text }}</p>
            </div>
            <!-- Assistant bubble -->
            <div v-else class="msg msg-assistant slide-up">
              <DiffCard v-if="msg.type === 'diff' && msg.diffData" :diff="msg.diffData" />
              <p v-else class="msg-text" :class="{ 'msg-warn': msg.type === 'clarification', 'msg-error': msg.type === 'error' }">
                {{ msg.text }}
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
      <EmptyState v-if="!itinerary && phase === 'idle'" />

      <!-- Error state with retry -->
      <ErrorState
        v-else-if="phase === 'error' && !itinerary"
        :errorText="errorText"
        @retry="retryLast"
        @reset="resetPlanner"
      />

      <!-- Loading state -->
      <div v-else-if="!itinerary && (phase === 'planning' || phase === 'editing')" class="loading-state">
        <div class="ld-ring" />
        <p class="ld-text">正在为你规划行程…</p>
      </div>

      <!-- Itinerary content -->
      <div v-if="itinerary" class="itinerary-content">
        <TripOverview
          :profile="itinerary.trip_profile"
          :dayCount="itinerary.days.length"
        />
        <ItineraryTimeline :days="itinerary.days" />
        <BudgetCard
          v-if="itinerary.budget_summary"
          :budget="itinerary.budget_summary"
        />
        <section v-if="itinerary.validation?.assumptions?.length" class="assumptions fade-in">
          <p
            v-for="(note, i) in itinerary.validation!.assumptions"
            :key="i"
            class="asm-item"
          >{{ note }}</p>
        </section>
      </div>
    </main>

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
import type { ItineraryResult, PlannerPhase, EditDiffData, ChatEntry } from '../types/itinerary'

import InputBar from '../components/chat/InputBar.vue'
import PhaseIndicator from '../components/chat/PhaseIndicator.vue'
import DiffCard from '../components/chat/DiffCard.vue'
import EmptyState from '../components/itinerary/EmptyState.vue'
import ErrorState from '../components/itinerary/ErrorState.vue'
import TripOverview from '../components/itinerary/TripOverview.vue'
import BudgetCard from '../components/itinerary/BudgetCard.vue'
import ItineraryTimeline from '../components/itinerary/ItineraryTimeline.vue'

// ---------- State ----------

const router = useRouter()
const conversationId = ref<string | null>(null)
const phase = ref<PlannerPhase>('idle')
const liveClarification = ref('')
const errorText = ref('')
const itinerary = ref<ItineraryResult | null>(null)
const isStreaming = ref(false)
const currentIntent = ref('')
const editDiff = ref<EditDiffData | null>(null)
const chatHistory = ref<ChatEntry[]>([])
const lastQuery = ref('')
let msgSeq = 0

const activeTab = ref<'chat' | 'itinerary'>('chat')
const isNarrow = ref(false)
const chatScrollRef = ref<HTMLElement | null>(null)
const itineraryScrollRef = ref<HTMLElement | null>(null)
const inputBarRef = ref<InstanceType<typeof InputBar> | null>(null)

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

const canReset = computed(() =>
  phase.value !== 'idle' ||
  Boolean(itinerary.value) ||
  chatHistory.value.length > 0
)

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

// ---------- Actions ----------

const resetPlanner = async () => {
  conversationId.value = null
  phase.value = 'idle'
  isStreaming.value = false
  liveClarification.value = ''
  errorText.value = ''
  itinerary.value = null
  currentIntent.value = ''
  editDiff.value = null
  chatHistory.value = []
  lastQuery.value = ''
  msgSeq = 0
  await nextTick()
  inputBarRef.value?.focus()
}

const goHome = () => router.push('/')

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
  phase.value = 'planning'
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
          }
        },
        onStageStart: () => {
          phase.value = 'clarifying'
        },
        onStageProgress: (envelope) => {
          phase.value = 'clarifying'
          liveClarification.value = envelope.payload.message || ''
        },
        onFinalItinerary: (envelope) => {
          phase.value = 'done'
          itinerary.value = envelope.payload.itinerary as ItineraryResult
          const explanation = envelope.payload.explanation || ''
          if (explanation) {
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
  flex-direction: column;
  height: 100vh;
  background: var(--bg-deep);
  color: var(--text);
  font-family: 'Inter', 'Noto Sans SC', system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
}

/* ==================== Tab Bar (mobile) ==================== */

.tab-bar {
  display: flex;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
}

.tab-btn {
  flex: 1;
  padding: 10px 0;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.tab-btn.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-btn:hover:not(.active) {
  color: var(--text-sec);
}

/* ==================== Dual Panel Layout ==================== */

.chat-panel,
.itinerary-panel {
  overflow: hidden;
}

/* Desktop: side by side */
@media (min-width: 768px) {
  .page {
    flex-direction: column;
  }

  .page > .chat-panel,
  .page > .itinerary-panel {
    flex: 1;
  }

  /* Use a wrapper-like approach via page being a grid on desktop */
  .page {
    display: grid;
    grid-template-columns: 2fr 3fr;
    grid-template-rows: 1fr auto;
  }

  .chat-panel {
    grid-column: 1;
    grid-row: 1;
    border-right: 1px solid var(--border);
  }

  .itinerary-panel {
    grid-column: 2;
    grid-row: 1;
  }

  /* InputBar spans full width */
  .page > :deep(.input-bar) {
    grid-column: 1 / -1;
    grid-row: 2;
  }
}

/* Mobile: stacked with tabs */
@media (max-width: 767px) {
  .page {
    display: flex;
    flex-direction: column;
  }

  .tab-bar {
    flex-shrink: 0;
  }

  .chat-panel,
  .itinerary-panel {
    flex: 1;
    min-height: 0;
  }
}

/* ==================== Chat Panel ==================== */

.chat-panel {
  display: flex;
  flex-direction: column;
  background: var(--bg);
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.nav {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-shrink: 0;
}

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

.brand-name {
  margin: 0;
  font-size: 20px;
  font-weight: 300;
  letter-spacing: -0.03em;
  background: linear-gradient(135deg, #e0f2fe 0%, #0ea5e9 55%, #0284c7 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* ---- Chat Messages ---- */

.chat-messages {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chat-hint {
  margin: auto 0;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
  padding: 40px 10px;
}

.msg {
  max-width: 92%;
  animation: slideUp 0.3s ease-out both;
}

.msg-user {
  align-self: flex-end;
}

.msg-user .msg-text {
  background: var(--accent);
  color: #fff;
  border-radius: var(--r-md) var(--r-md) 4px var(--r-md);
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.6;
}

.msg-assistant {
  align-self: flex-start;
}

.msg-assistant > .msg-text {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md) var(--r-md) var(--r-md) 4px;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
}

.msg-text {
  margin: 0;
  word-break: break-word;
  white-space: pre-wrap;
}

.msg-warn {
  color: #fde68a !important;
  border-color: rgba(245, 158, 11, 0.2) !important;
}

.msg-error {
  color: #fca5a5 !important;
  border-color: rgba(239, 68, 68, 0.2) !important;
}

/* ==================== Itinerary Panel ==================== */

.itinerary-panel {
  overflow-y: auto;
  padding: 36px 36px 36px 44px;
  scroll-behavior: smooth;
  background: var(--bg-deep);
}

.itinerary-content {
  max-width: 700px;
}

/* ---- Loading ---- */

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

@keyframes spin { to { transform: rotate(360deg); } }

/* ---- Assumptions ---- */

.assumptions { padding: 0; margin-top: 16px; }

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

/* ==================== Animations ==================== */

.fade-in { animation: fadeIn 0.4s ease-out both; }
.slide-up { animation: slideUp 0.3s ease-out both; }

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ==================== Responsive ==================== */

@media (max-width: 767px) {
  .itinerary-panel { padding: 20px 16px; }
  .chat-scroll { padding: 16px; }
  .brand-name { font-size: 18px; }
}
</style>
