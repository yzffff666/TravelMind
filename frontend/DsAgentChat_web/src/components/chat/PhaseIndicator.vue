<template>
  <GlassCard v-if="phase !== 'idle'" class="phase-indicator">
    <div class="phase-indicator__glow" aria-hidden="true" />
    <div class="phase-indicator__content">
      <StatusBadge :tone="tone">
        {{ label }}
      </StatusBadge>
      <p class="phase-indicator__copy">{{ description }}</p>
    </div>
    <span v-if="isActive" class="phase-indicator__pulse" aria-hidden="true" />
  </GlassCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PlannerPhase } from '../../types/itinerary'
import { GlassCard, StatusBadge } from '../ui'

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

const description = computed(() => {
  switch (props.phase) {
    case 'planning': return '正在把对话、证据和地图点位整理成可浏览的旅行叙事。'
    case 'editing': return '正在保留原行程结构，仅重写你指定的片段。'
    case 'clarifying': return '还需要补充一个关键信息，才能继续生成可靠行程。'
    case 'done': return '行程已更新，可继续追问、调整或查看地图。'
    case 'error': return '当前请求没有完成，可以调整输入后重试。'
    default: return ''
  }
})

const tone = computed<'neutral' | 'info' | 'success' | 'warning' | 'danger'>(() => {
  switch (props.phase) {
    case 'planning': return 'info'
    case 'editing': return 'warning'
    case 'clarifying': return 'warning'
    case 'done': return 'success'
    case 'error': return 'danger'
    default: return 'neutral'
  }
})
</script>

<style scoped>
.phase-indicator {
  position: relative;
  display: grid;
  gap: var(--tm-space-3);
  max-width: 440px;
  margin-bottom: var(--tm-space-2);
  padding: var(--tm-space-4);
  overflow: hidden;
}

.phase-indicator__glow {
  position: absolute;
  inset: auto -20% -60% 20%;
  height: 90px;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.2), transparent 68%);
  pointer-events: none;
}

.phase-indicator__content {
  position: relative;
  display: grid;
  gap: var(--tm-space-2);
}

.phase-indicator__copy {
  max-width: 36em;
  margin: 0;
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-xs);
  line-height: var(--tm-line-height-normal);
}

.phase-indicator__pulse {
  position: absolute;
  right: var(--tm-space-4);
  top: var(--tm-space-4);
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--tm-color-cyan);
  box-shadow: 0 0 0 0 rgba(34, 211, 238, 0.36);
  animation: phase-pulse 1.5s ease-out infinite;
}

@keyframes phase-pulse {
  70% {
    box-shadow: 0 0 0 12px rgba(34, 211, 238, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(34, 211, 238, 0);
  }
}
</style>
