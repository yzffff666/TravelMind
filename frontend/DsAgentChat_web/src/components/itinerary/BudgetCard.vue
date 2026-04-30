<template>
  <GlassCard class="budget-card fade-in">
    <div class="bgt-header">
      <div>
        <span class="bgt-label">Budget estimate</span>
        <h3 class="bgt-title">预算概览</h3>
      </div>
      <span class="bgt-total">&yen;{{ fmt(budget.total_estimate) }}</span>
    </div>
    <div v-if="categories.length" class="bgt-bars">
      <div
        v-for="(cat, ci) in categories"
        :key="cat.label"
        class="bgt-row"
        :style="{ animationDelay: `${ci * 0.08 + 0.15}s` }"
      >
        <div class="bgt-row-top">
          <span class="bgt-dot" :class="`bgt-dot--${cat.tone}`" />
          <span class="bgt-cat">{{ cat.label }}</span>
          <span class="bgt-amt">&yen;{{ fmt(cat.value) }}</span>
        </div>
        <div class="bgt-track">
          <div
            class="bgt-fill"
            :class="`bgt-fill--${cat.tone}`"
            :style="{ '--target-width': cat.percent + '%' }"
          />
        </div>
      </div>
    </div>
    <p v-if="budget.uncertainty_note" class="bgt-note">
      <StatusBadge tone="warning">预算浮动</StatusBadge>
      {{ budget.uncertainty_note }}
    </p>
  </GlassCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { BudgetSummary } from '../../types/itinerary'
import { GlassCard, StatusBadge } from '../ui'

const props = defineProps<{ budget: BudgetSummary }>()

const fmt = (n: number) => Math.round(n).toLocaleString('zh-CN')

const categories = computed(() => {
  const cat = props.budget.by_category
  if (!cat) return []
  const total = props.budget.total_estimate || 1
  const mapping: [string, number | null | undefined, string][] = [
    ['交通', cat.transport, 'info'],
    ['住宿', cat.hotel, 'violet'],
    ['门票', cat.tickets, 'warning'],
    ['餐饮', cat.food, 'success'],
    ['其他', cat.other, 'neutral'],
  ]
  return mapping
    .filter(([, v]) => v && v > 0)
    .map(([label, value, tone]) => ({
      label,
      value: value as number,
      tone,
      percent: Math.round(((value as number) / total) * 100),
    }))
})
</script>

<style scoped>
.budget-card {
  padding: var(--tm-space-5);
  margin-bottom: 16px;
}

.bgt-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--tm-space-4);
  margin-bottom: var(--tm-space-5);
}

.bgt-label {
  display: block;
  margin-bottom: var(--tm-space-1);
  font-size: var(--tm-font-size-xs);
  font-weight: 800;
  color: var(--tm-color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.12em;
}

.bgt-title {
  margin: 0;
  color: var(--tm-color-text-primary);
  font-size: var(--tm-font-size-lg);
  font-weight: 800;
  line-height: var(--tm-line-height-tight);
}

.bgt-total {
  font-size: var(--tm-font-size-xl);
  font-weight: 800;
  color: var(--tm-color-warning);
  letter-spacing: -0.02em;
  white-space: nowrap;
}

.bgt-bars {
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-3);
}

.bgt-row { animation: fadeIn 0.4s ease-out both; }

.bgt-row-top {
  display: flex;
  align-items: center;
  gap: var(--tm-space-2);
  margin-bottom: var(--tm-space-2);
}

.bgt-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}

.bgt-dot--info,
.bgt-fill--info { background: var(--tm-color-info); }

.bgt-dot--violet,
.bgt-fill--violet { background: var(--tm-color-violet); }

.bgt-dot--warning,
.bgt-fill--warning { background: var(--tm-color-warning); }

.bgt-dot--success,
.bgt-fill--success { background: var(--tm-color-success); }

.bgt-dot--neutral,
.bgt-fill--neutral { background: var(--tm-color-text-muted); }

.bgt-cat { font-size: var(--tm-font-size-xs); color: var(--tm-color-text-secondary); }

.bgt-amt {
  margin-left: auto;
  font-size: var(--tm-font-size-xs);
  font-weight: 500;
  color: var(--tm-color-text-primary);
}

.bgt-track {
  height: 6px;
  background: rgba(148, 163, 184, 0.12);
  border-radius: var(--tm-radius-pill);
  overflow: hidden;
}

.bgt-fill {
  height: 100%;
  border-radius: var(--tm-radius-pill);
  width: var(--target-width);
  transform-origin: left;
  animation: barScale 0.8s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes barScale {
  from { transform: scaleX(0); }
  to   { transform: scaleX(1); }
}

.bgt-note {
  display: flex;
  align-items: flex-start;
  gap: var(--tm-space-2);
  margin: var(--tm-space-4) 0 0;
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-xs);
  line-height: var(--tm-line-height-normal);
}

.fade-in { animation: fadeIn 0.4s ease-out both; }

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}
</style>
