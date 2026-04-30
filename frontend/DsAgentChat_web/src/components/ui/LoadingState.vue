<template>
  <div class="tm-loading-state" role="status" aria-live="polite">
    <span class="tm-loading-state__spinner" aria-hidden="true" />
    <div>
      <p class="tm-loading-state__title">{{ title }}</p>
      <p v-if="description" class="tm-loading-state__description">{{ description }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  description?: string
}>(), {
  title: '正在处理',
  description: ''
})
</script>

<style scoped>
.tm-loading-state {
  display: inline-flex;
  align-items: center;
  gap: var(--tm-space-3);
  padding: var(--tm-space-4);
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-xl);
  background: rgba(15, 23, 42, 0.58);
  color: var(--tm-color-text-primary);
}

.tm-loading-state__spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--tm-color-border);
  border-top-color: var(--tm-color-cyan);
  border-radius: 50%;
  animation: tm-spin 0.8s linear infinite;
}

.tm-loading-state__title,
.tm-loading-state__description {
  margin: 0;
}

.tm-loading-state__title {
  font-size: var(--tm-font-size-sm);
  font-weight: 700;
}

.tm-loading-state__description {
  margin-top: var(--tm-space-1);
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-xs);
}

@keyframes tm-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
