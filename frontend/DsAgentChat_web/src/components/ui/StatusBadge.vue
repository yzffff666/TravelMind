<template>
  <span class="tm-status-badge" :class="`tm-status-badge--${tone}`">
    <span class="tm-status-badge__dot" aria-hidden="true" />
    <slot />
  </span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  tone?: 'neutral' | 'info' | 'success' | 'warning' | 'danger'
}>(), {
  tone: 'neutral'
})
</script>

<style scoped>
.tm-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 0 var(--tm-space-3);
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-pill);
  background: rgba(15, 23, 42, 0.58);
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-xs);
  font-weight: 700;
  letter-spacing: 0.01em;
}

.tm-status-badge__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 16px currentColor;
}

.tm-status-badge--info {
  color: var(--tm-color-info);
  border-color: rgba(56, 189, 248, 0.28);
}

.tm-status-badge--success {
  color: var(--tm-color-success);
  border-color: rgba(52, 211, 153, 0.28);
}

.tm-status-badge--warning {
  color: var(--tm-color-warning);
  border-color: rgba(251, 191, 36, 0.32);
}

.tm-status-badge--danger {
  color: var(--tm-color-danger);
  border-color: rgba(251, 113, 133, 0.32);
}
</style>
