<template>
  <div class="page">
    <!-- Scrollable content area -->
    <div ref="scrollRef" class="scroll-area">
      <!-- Nav -->
      <nav class="nav">
        <button class="nav-back" @click="goHome">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          返回首页
        </button>
      </nav>

      <!-- Hero -->
      <header class="hero">
        <h1 class="hero-title">TravelMind</h1>
        <p class="hero-sub">描述你的旅行需求，AI 为你生成可编辑的行程草案</p>
      </header>

      <div class="body">
        <!-- Input card -->
        <section class="card input-card">
          <label class="label">旅行需求</label>
          <div class="textarea-wrap" :class="{ focused: isTextareaFocused, disabled: isStreaming }">
            <textarea
              ref="textareaRef"
              v-model="query"
              :disabled="isStreaming"
              rows="4"
              placeholder="上海 4 天，预算 6000，情侣出行，喜欢文化体验和地道美食"
              @focus="isTextareaFocused = true"
              @blur="isTextareaFocused = false"
            />
          </div>
          <p class="field-hint">支持自由描述：目的地、天数、预算、出行人群、偏好等</p>
        </section>

        <!-- Status / messages -->
        <section v-if="phase !== 'idle'" class="card status-card">
          <div class="status-row">
            <span class="badge" :class="statusClass">
              <span v-if="phase === 'planning'" class="badge-dot pulse" />
              <span v-else class="badge-dot" :class="statusClass" />
              {{ statusText }}
            </span>
          </div>
          <p v-if="clarificationMessage" class="msg msg-warn">{{ clarificationMessage }}</p>
          <p v-if="errorText" class="msg msg-error">{{ errorText }}</p>
          <p v-if="finalText" class="msg">{{ finalText }}</p>
          <p v-if="explanation" class="msg msg-muted">{{ explanation }}</p>
        </section>

        <!-- Empty state -->
        <section v-if="phase === 'idle'" class="empty-state">
          <div class="empty-icon">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <rect x="4" y="8" width="40" height="32" rx="4" stroke="currentColor" stroke-width="1.5"/>
              <path d="M4 16h40M16 16v24" stroke="currentColor" stroke-width="1.5"/>
              <circle cx="32" cy="28" r="4" stroke="currentColor" stroke-width="1.5"/>
              <path d="M32 32v4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </div>
          <p class="empty-title">还没有行程草案</p>
          <p class="empty-sub">在上方输入旅行需求，点击「生成行程草案」即可开始</p>
        </section>

        <!-- Result -->
        <section v-if="itinerary" ref="resultRef" class="card result-card">
          <h2 class="section-title">推荐行程</h2>
          <div v-for="day in itinerary.days" :key="day.day_index" class="day">
            <div class="day-header">
              <span class="day-badge">Day {{ day.day_index }}</span>
            </div>
            <ul class="slot-list">
              <li v-for="slot in day.slots" :key="`${day.day_index}-${slot.slot}-${slot.activity}`" class="slot-item">
                <span class="slot-time">{{ slot.slot }}</span>
                <span class="slot-desc">{{ slot.activity }}</span>
              </li>
            </ul>
          </div>
        </section>
      </div>
    </div>

    <!-- Fixed action bar — outside scroll area, never overlaps content -->
    <div class="action-bar">
      <div class="action-bar-inner">
        <button
          class="btn-primary"
          :disabled="isStreaming || !query.trim()"
          @click="submitQuery"
        >
          <svg v-if="isStreaming" class="spinner" width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="32" stroke-dashoffset="10" stroke-linecap="round"/></svg>
          {{ isStreaming ? '正在规划…' : '生成行程草案' }}
        </button>
        <button
          v-if="canReset"
          class="btn-ghost"
          :disabled="isStreaming"
          @click="resetPlanner"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M2 8a6 6 0 0 1 10.3-4.2L14 2v5h-5l1.8-1.8A4 4 0 1 0 12 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          重新开始
        </button>
        <button
          v-if="itinerary || finalText || clarificationMessage"
          class="btn-ghost"
          @click="scrollToInput"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 12V4M5 7l3-3 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          回到输入
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiService } from '../services/api'

interface ItinerarySlot {
  slot: string
  activity: string
}

interface ItineraryDay {
  day_index: number
  slots: ItinerarySlot[]
}

interface ItineraryResult {
  days: ItineraryDay[]
}

type PlannerPhase = 'idle' | 'clarifying' | 'planning' | 'done' | 'error'

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

const statusText = computed(() => {
  if (phase.value === 'planning') return '正在生成草案'
  if (phase.value === 'clarifying') return '需要补充信息'
  if (phase.value === 'done' && itinerary.value) return '草案已生成'
  if (phase.value === 'done') return '已完成'
  if (phase.value === 'error') return '请求失败'
  return '等待输入'
})

const statusClass = computed(() => {
  if (phase.value === 'planning') return 'badge-planning'
  if (phase.value === 'clarifying') return 'badge-warn'
  if (phase.value === 'done') return 'badge-success'
  if (phase.value === 'error') return 'badge-error'
  return 'badge-idle'
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

const resetResultState = () => {
  clarificationMessage.value = ''
  finalText.value = ''
  explanation.value = ''
  errorText.value = ''
  itinerary.value = null
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

const goHome = () => {
  router.push('/')
}

const scrollToInput = () => {
  scrollRef.value?.scrollTo({ top: 0, behavior: 'smooth' })
  setTimeout(() => textareaRef.value?.focus(), 400)
}

const scrollToResult = async () => {
  await nextTick()
  if (resultRef.value && scrollRef.value) {
    const top = resultRef.value.offsetTop - scrollRef.value.offsetTop
    scrollRef.value.scrollTo({ top, behavior: 'smooth' })
  }
}

const submitQuery = async () => {
  if (!query.value.trim()) return
  const userId = localStorage.getItem('user_id')
  if (!userId) {
    errorText.value = '缺少 user_id，请重新登录后重试。'
    phase.value = 'error'
    return
  }

  resetResultState()
  phase.value = 'planning'
  isStreaming.value = true

  try {
    const result = await ApiService.travelQueryStream(
      {
        query: query.value.trim(),
        userId,
        conversationId: conversationId.value || undefined
      },
      {
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
        }
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

<style scoped>
/* ===== Page + Design Tokens ===== */
.page {
  --bg: #0f0f12;
  --bg-raised: #18181c;
  --bg-card: #1c1c22;
  --border: #2a2a32;
  --border-hover: #3a3a44;
  --text-primary: #ececef;
  --text-secondary: #a0a0ab;
  --text-muted: #6b6b78;
  --accent: #6366f1;
  --accent-hover: #818cf8;
  --accent-muted: rgba(99, 102, 241, 0.12);
  --warn: #f59e0b;
  --warn-muted: rgba(245, 158, 11, 0.12);
  --success: #22c55e;
  --success-muted: rgba(34, 197, 94, 0.10);
  --error: #ef4444;
  --error-muted: rgba(239, 68, 68, 0.10);
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;

  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans SC', sans-serif;
  -webkit-font-smoothing: antialiased;
}

/* ===== Scroll Area ===== */
.scroll-area {
  flex: 1;
  overflow-y: auto;
  scroll-behavior: smooth;
}

/* ===== Nav ===== */
.nav {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px 24px 0;
}

.nav-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px 6px 8px;
  font-size: 13px;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.nav-back:hover {
  color: var(--text-primary);
  border-color: var(--border-hover);
  background: var(--bg-raised);
}

/* ===== Hero ===== */
.hero {
  max-width: 800px;
  margin: 0 auto;
  padding: 40px 24px 8px;
  text-align: center;
}

.hero-title {
  margin: 0;
  font-size: 36px;
  font-weight: 700;
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, #c7d2fe 0%, #818cf8 50%, #6366f1 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-sub {
  margin: 12px 0 0;
  font-size: 15px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* ===== Body container ===== */
.body {
  max-width: 800px;
  margin: 0 auto;
  padding: 32px 24px 32px;
}

/* ===== Cards ===== */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  margin-bottom: 16px;
}

/* ===== Input Card ===== */
.label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.textarea-wrap {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.textarea-wrap.focused {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-muted);
}

.textarea-wrap.disabled {
  opacity: 0.6;
}

textarea {
  display: block;
  width: 100%;
  border: none;
  background: transparent;
  color: var(--text-primary);
  padding: 14px 16px;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  border-radius: var(--radius-md);
  font-family: inherit;
}

textarea:focus {
  outline: none;
}

textarea::placeholder {
  color: var(--text-muted);
}

.field-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

/* ===== Action Bar (pinned at bottom, outside scroll) ===== */
.action-bar {
  flex-shrink: 0;
  background: var(--bg-raised);
  border-top: 1px solid var(--border);
}

.action-bar-inner {
  max-width: 800px;
  margin: 0 auto;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 500;
  font-family: inherit;
  color: #fff;
  background: var(--accent);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.15s, transform 0.1s, box-shadow 0.15s;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.32);
}

.btn-primary:active:not(:disabled) {
  transform: scale(0.98);
}

.btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-ghost {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 10px 16px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}

.btn-ghost:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--border-hover);
  background: var(--bg-raised);
}

.btn-ghost:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* Spinner */
.spinner {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ===== Status Card ===== */
.status-card {
  padding: 16px 24px;
}

.status-row {
  display: flex;
  align-items: center;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid transparent;
}

.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.badge-idle {
  background: var(--bg-raised);
  border-color: var(--border);
  color: var(--text-muted);
}

.badge-idle .badge-dot { background: var(--text-muted); }

.badge-planning {
  background: var(--accent-muted);
  border-color: rgba(99, 102, 241, 0.28);
  color: #c7d2fe;
}

.badge-planning .badge-dot { background: var(--accent); }

.badge-warn {
  background: var(--warn-muted);
  border-color: rgba(245, 158, 11, 0.28);
  color: #fde68a;
}

.badge-warn .badge-dot { background: var(--warn); }

.badge-success {
  background: var(--success-muted);
  border-color: rgba(34, 197, 94, 0.28);
  color: #bbf7d0;
}

.badge-success .badge-dot { background: var(--success); }

.badge-error {
  background: var(--error-muted);
  border-color: rgba(239, 68, 68, 0.28);
  color: #fecaca;
}

.badge-error .badge-dot { background: var(--error); }

.pulse {
  animation: pulse-ring 1.2s ease-in-out infinite;
}

@keyframes pulse-ring {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.msg {
  margin: 12px 0 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
}

.msg-warn { color: #fde68a; }
.msg-error { color: #fca5a5; }
.msg-muted { color: var(--text-secondary); }

/* ===== Empty State ===== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 56px 24px;
  text-align: center;
}

.empty-icon {
  color: var(--text-muted);
  opacity: 0.45;
  margin-bottom: 16px;
}

.empty-title {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--text-secondary);
}

.empty-sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-muted);
  max-width: 320px;
}

/* ===== Result Card ===== */
.section-title {
  margin: 0 0 16px;
  font-size: 18px;
  font-weight: 600;
}

.day {
  padding: 16px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  margin-bottom: 12px;
}

.day:last-child {
  margin-bottom: 0;
}

.day-header {
  margin-bottom: 12px;
}

.day-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  background: var(--accent-muted);
  border-radius: 999px;
}

.slot-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.slot-item {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  border-top: 1px solid var(--border);
  font-size: 14px;
  line-height: 1.5;
}

.slot-item:first-child {
  border-top: none;
  padding-top: 0;
}

.slot-time {
  flex-shrink: 0;
  width: 48px;
  color: var(--accent-hover);
  font-weight: 500;
  font-size: 13px;
}

.slot-desc {
  color: var(--text-primary);
}

/* ===== Responsive ===== */
@media (max-width: 640px) {
  .hero { padding: 28px 16px 4px; }
  .hero-title { font-size: 28px; }
  .hero-sub { font-size: 14px; }
  .nav { padding: 16px 16px 0; }
  .body { padding: 24px 16px 24px; }
  .card { padding: 16px; }
  .status-card { padding: 12px 16px; }
  .day { padding: 12px; }
  .empty-state { padding: 40px 16px; }
  .action-bar-inner { padding: 10px 16px; }
}
</style>
