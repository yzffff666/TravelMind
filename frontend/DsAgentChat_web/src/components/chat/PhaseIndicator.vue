<template>
  <GlassCard
    v-if="phase !== 'idle'"
    class="phase-indicator"
    :class="`phase-indicator--${phase}`"
  >
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
import { useI18n } from 'vue-i18n'
import type { PlannerPhase } from '../../types/itinerary'
import { GlassCard, StatusBadge } from '../ui'

const props = defineProps<{
  phase: PlannerPhase
  intentLabel: string
  intent?: string
}>()

const { locale, t } = useI18n()

const isActive = computed(() =>
  props.phase === 'planning' || props.phase === 'editing' || props.phase === 'clarifying'
)

const label = computed(() => {
  const suffix = props.intentLabel
    ? locale.value === 'zh-CN' ? `（${props.intentLabel}）` : ` (${props.intentLabel})`
    : ''
  switch (props.phase) {
    case 'planning': return t('phase.label.planning', { suffix })
    case 'editing': return t('phase.label.editing', { suffix })
    case 'clarifying': return t('phase.label.clarifying')
    case 'done': return t('phase.label.done', { suffix })
    case 'error': return t('phase.label.error')
    default: return ''
  }
})

const description = computed(() => {
  switch (props.phase) {
    case 'planning': return t('phase.description.planning')
    case 'editing': return t('phase.description.editing')
    case 'clarifying': return t('phase.description.clarifying')
    case 'done':
      if (props.intent === 'qa') return t('phase.description.qaDone')
      if (props.intent === 'reset') return t('phase.description.resetDone')
      return t('phase.description.done')
    case 'error': return t('phase.description.error')
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
  background: radial-gradient(circle, rgba(198, 161, 91, 0.2), transparent 68%);
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
  box-shadow: 0 0 0 0 rgba(216, 192, 138, 0.36);
  animation: phase-pulse 1.5s ease-out infinite;
}

@keyframes phase-pulse {
  70% {
    box-shadow: 0 0 0 12px rgba(216, 192, 138, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(216, 192, 138, 0);
  }
}
</style>
