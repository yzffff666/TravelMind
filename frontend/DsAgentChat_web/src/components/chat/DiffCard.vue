<template>
  <GlassCard class="diff-card">
    <div class="diff-header">
      <div class="diff-icon-wrap" aria-hidden="true">
        <svg class="diff-icon" width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <div>
        <StatusBadge class="diff-title" tone="warning">行程已修改</StatusBadge>
        <p class="diff-kicker">已按你的要求更新 itinerary 片段</p>
      </div>
    </div>

    <ul v-if="diff.summary.diff_items.length" class="diff-list">
      <li
        v-for="(item, i) in diff.summary.diff_items"
        :key="i"
        class="diff-item"
      >{{ item }}</li>
    </ul>

    <div v-if="diff.summary.changed_days.length" class="diff-days">
      <span class="diff-days-label">涉及天数</span>
      <StatusBadge
        v-for="d in diff.summary.changed_days"
        :key="d"
        class="diff-day-tag"
        tone="info"
      >第 {{ d }} 天</StatusBadge>
    </div>

    <p v-if="diff.explanation" class="diff-explanation">{{ diff.explanation }}</p>
  </GlassCard>
</template>

<script setup lang="ts">
import type { EditDiffData } from '../../types/itinerary'
import { GlassCard, StatusBadge } from '../ui'

defineProps<{ diff: EditDiffData }>()
</script>

<style scoped>
.diff-card {
  position: relative;
  max-width: 520px;
  padding: var(--tm-space-5);
  overflow: hidden;
}

.diff-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--tm-gradient-brand);
  opacity: 0.9;
}

.diff-header {
  display: flex;
  align-items: center;
  gap: var(--tm-space-3);
  margin-bottom: var(--tm-space-4);
}

.diff-icon-wrap {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-lg);
  background: var(--tm-color-primary-soft);
  color: var(--tm-color-cyan);
}

.diff-icon {
  flex-shrink: 0;
}

.diff-kicker {
  margin: var(--tm-space-2) 0 0;
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-xs);
  line-height: var(--tm-line-height-normal);
}

.diff-list {
  display: grid;
  gap: var(--tm-space-2);
  margin: 0 0 var(--tm-space-4);
  padding: 0 0 0 18px;
  list-style: none;
}

.diff-item {
  position: relative;
  color: var(--tm-color-text-primary);
  font-size: var(--tm-font-size-sm);
  line-height: var(--tm-line-height-normal);
  padding-left: var(--tm-space-1);
}

.diff-item::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 0.7em;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--tm-color-cyan);
  box-shadow: 0 0 14px rgba(216, 192, 138, 0.34);
}

.diff-days {
  display: flex;
  align-items: center;
  gap: var(--tm-space-2);
  flex-wrap: wrap;
}

.diff-days-label {
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-xs);
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.diff-explanation {
  margin: var(--tm-space-4) 0 0;
  padding-top: var(--tm-space-4);
  border-top: 1px solid var(--tm-color-border);
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-xs);
  line-height: var(--tm-line-height-normal);
}
</style>
