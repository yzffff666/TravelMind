<template>
  <section class="tm-glass-card" :class="{ 'tm-glass-card--interactive': interactive }">
    <slot />
  </section>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  interactive?: boolean
}>(), {
  interactive: false
})
</script>

<style scoped>
.tm-glass-card {
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-2xl);
  background: var(--tm-gradient-surface);
  box-shadow: var(--tm-shadow-card);
  backdrop-filter: var(--tm-blur-glass);
}

.tm-glass-card--interactive {
  transition:
    transform var(--tm-motion-normal),
    border-color var(--tm-motion-normal),
    box-shadow var(--tm-motion-normal);
}

.tm-glass-card--interactive:hover {
  transform: translateY(-2px);
  border-color: var(--tm-color-border-strong);
  box-shadow: var(--tm-shadow-card), var(--tm-shadow-glow);
}
</style>
