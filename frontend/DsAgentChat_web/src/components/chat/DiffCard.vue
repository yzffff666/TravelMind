<template>
  <div class="diff-card">
    <div class="diff-header">
      <svg class="diff-icon" width="16" height="16" viewBox="0 0 24 24" fill="none">
        <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <span class="diff-title">行程已修改</span>
    </div>

    <ul v-if="diff.summary.diff_items.length" class="diff-list">
      <li
        v-for="(item, i) in diff.summary.diff_items"
        :key="i"
        class="diff-item"
      >{{ item }}</li>
    </ul>

    <div v-if="diff.summary.changed_days.length" class="diff-days">
      <span class="diff-days-label">涉及天数：</span>
      <span
        v-for="d in diff.summary.changed_days"
        :key="d"
        class="diff-day-tag"
      >第 {{ d }} 天</span>
    </div>

    <p v-if="diff.explanation" class="diff-explanation">{{ diff.explanation }}</p>
  </div>
</template>

<script setup lang="ts">
import type { EditDiffData } from '../../types/itinerary'

defineProps<{ diff: EditDiffData }>()
</script>

<style scoped>
.diff-card {
  background: var(--bg-card);
  border: 1px solid rgba(167, 139, 250, 0.2);
  border-radius: var(--r-md);
  padding: 14px 16px;
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
</style>
