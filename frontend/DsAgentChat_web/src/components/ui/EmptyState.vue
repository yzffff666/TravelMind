<template>
  <GlassCard class="tm-empty-state">
    <div class="tm-empty-state__icon" aria-hidden="true">
      <slot name="icon">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M4 18c4-8 8-12 16-12-4 4-6 8-6 14-2-3-5-4-10-2Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
          <path d="M10 14 7 21" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
        </svg>
      </slot>
    </div>
    <h2>{{ title }}</h2>
    <p>{{ description }}</p>
    <div v-if="$slots.default" class="tm-empty-state__actions">
      <slot />
    </div>
  </GlassCard>
</template>

<script setup lang="ts">
import GlassCard from './GlassCard.vue'

defineProps<{
  title: string
  description: string
}>()
</script>

<style scoped>
.tm-empty-state {
  display: grid;
  justify-items: center;
  gap: var(--tm-space-4);
  padding: var(--tm-space-10);
  text-align: center;
}

.tm-empty-state__icon {
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
  border-radius: var(--tm-radius-2xl);
  background: var(--tm-color-primary-soft);
  color: var(--tm-color-cyan);
  box-shadow: var(--tm-shadow-glow);
}

.tm-empty-state__icon svg {
  width: 34px;
  height: 34px;
}

.tm-empty-state h2 {
  margin: 0;
  color: var(--tm-color-text-primary);
  font-size: var(--tm-font-size-xl);
  line-height: var(--tm-line-height-tight);
}

.tm-empty-state p {
  max-width: 520px;
  margin: 0;
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-sm);
  line-height: var(--tm-line-height-normal);
}

.tm-empty-state__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--tm-space-3);
}
</style>
