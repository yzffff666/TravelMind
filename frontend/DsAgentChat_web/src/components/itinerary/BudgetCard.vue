<template>
  <section class="budget-card fade-in">
    <div class="bgt-header">
      <span class="bgt-label">预算概览</span>
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
          <span class="bgt-dot" :style="{ background: cat.color }" />
          <span class="bgt-cat">{{ cat.label }}</span>
          <span class="bgt-amt">&yen;{{ fmt(cat.value) }}</span>
        </div>
        <div class="bgt-track">
          <div
            class="bgt-fill"
            :style="{ '--target-width': cat.percent + '%', background: cat.color }"
          />
        </div>
      </div>
    </div>
    <p v-if="budget.uncertainty_note" class="bgt-note">
      {{ budget.uncertainty_note }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { BudgetSummary } from '../../types/itinerary'

const props = defineProps<{ budget: BudgetSummary }>()

const fmt = (n: number) => Math.round(n).toLocaleString('zh-CN')

const categories = computed(() => {
  const cat = props.budget.by_category
  if (!cat) return []
  const total = props.budget.total_estimate || 1
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
</script>

<style scoped>
.budget-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 18px;
  margin-bottom: 16px;
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

.bgt-row { animation: fadeIn 0.4s ease-out both; }

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

.bgt-cat { font-size: 12px; color: var(--text-sec); }

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

.fade-in { animation: fadeIn 0.4s ease-out both; }

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}
</style>
