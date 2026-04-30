<template>
  <GlassCard class="tm-error-state">
    <StatusBadge tone="danger">需要处理</StatusBadge>
    <div>
      <h2>{{ title }}</h2>
      <p>{{ description }}</p>
    </div>
    <div v-if="$slots.default" class="tm-error-state__actions">
      <slot />
    </div>
  </GlassCard>
</template>

<script setup lang="ts">
import GlassCard from './GlassCard.vue'
import StatusBadge from './StatusBadge.vue'

withDefaults(defineProps<{
  title?: string
  description?: string
}>(), {
  title: '出现了一点问题',
  description: '请稍后重试，或调整输入后重新提交。'
})
</script>

<style scoped>
.tm-error-state {
  display: grid;
  gap: var(--tm-space-4);
  padding: var(--tm-space-8);
}

.tm-error-state h2 {
  margin: 0;
  color: var(--tm-color-text-primary);
  font-size: var(--tm-font-size-xl);
}

.tm-error-state p {
  max-width: 560px;
  margin: var(--tm-space-2) 0 0;
  color: var(--tm-color-text-secondary);
  line-height: var(--tm-line-height-normal);
}

.tm-error-state__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--tm-space-3);
}
</style>
