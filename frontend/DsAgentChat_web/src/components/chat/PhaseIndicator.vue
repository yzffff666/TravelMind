<template>
  <div v-if="phase !== 'idle'" class="phase-indicator">
    <div class="status-badge" :class="'st-' + phase">
      <span class="status-dot" :class="{ pulse: isActive }" />
      {{ label }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PlannerPhase } from '../../types/itinerary'

const props = defineProps<{
  phase: PlannerPhase
  intentLabel: string
}>()

const isActive = computed(() =>
  props.phase === 'planning' || props.phase === 'editing' || props.phase === 'clarifying'
)

const label = computed(() => {
  const suffix = props.intentLabel ? `（${props.intentLabel}）` : ''
  switch (props.phase) {
    case 'planning': return `正在生成草案${suffix}`
    case 'editing': return `正在编辑行程${suffix}`
    case 'clarifying': return '需要补充信息'
    case 'done': return `已完成${suffix}`
    case 'error': return '请求失败'
    default: return ''
  }
})
</script>

<style scoped>
.phase-indicator { margin-bottom: 4px; }

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
.st-editing { background: rgba(167, 139, 250, 0.12); color: #c4b5fd; }
.st-editing .status-dot { background: #a78bfa; }
.st-clarifying { background: var(--warn-soft); color: #fde68a; }
.st-clarifying .status-dot { background: var(--warn); }
.st-done { background: var(--success-soft); color: #bbf7d0; }
.st-done .status-dot { background: var(--success); }
.st-error { background: var(--error-soft); color: #fecaca; }
.st-error .status-dot { background: var(--error); }

.pulse { animation: pulse-ring 1.2s ease-in-out infinite; }

@keyframes pulse-ring {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
