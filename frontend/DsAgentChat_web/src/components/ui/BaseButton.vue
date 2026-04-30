<template>
  <button
    class="tm-button"
    :class="[`tm-button--${variant}`, `tm-button--${size}`, { 'is-loading': loading }]"
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading ? 'true' : 'false'"
  >
    <span v-if="loading" class="tm-button__spinner" aria-hidden="true" />
    <span class="tm-button__content">
      <slot />
    </span>
  </button>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  type?: 'button' | 'submit' | 'reset'
  loading?: boolean
  disabled?: boolean
}>(), {
  variant: 'primary',
  size: 'md',
  type: 'button',
  loading: false,
  disabled: false
})
</script>

<style scoped>
.tm-button {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--tm-space-2);
  border: 1px solid transparent;
  border-radius: var(--tm-radius-pill);
  font-weight: 700;
  line-height: 1;
  transition:
    transform var(--tm-motion-fast),
    border-color var(--tm-motion-fast),
    background var(--tm-motion-fast),
    box-shadow var(--tm-motion-fast),
    opacity var(--tm-motion-fast);
}

.tm-button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.tm-button:active:not(:disabled) {
  transform: translateY(0);
}

.tm-button:focus-visible {
  box-shadow: var(--tm-shadow-focus);
}

.tm-button:disabled {
  opacity: 0.52;
}

.tm-button--sm {
  min-height: 36px;
  padding: 0 var(--tm-space-4);
  font-size: var(--tm-font-size-sm);
}

.tm-button--md {
  padding: 0 var(--tm-space-5);
  font-size: var(--tm-font-size-sm);
}

.tm-button--lg {
  min-height: 52px;
  padding: 0 var(--tm-space-6);
  font-size: var(--tm-font-size-md);
}

.tm-button--primary {
  color: var(--tm-color-text-primary);
  background: var(--tm-gradient-brand);
  box-shadow: var(--tm-shadow-glow);
}

.tm-button--secondary {
  color: var(--tm-color-text-primary);
  background: var(--tm-color-surface-elevated);
  border-color: var(--tm-color-border);
}

.tm-button--ghost {
  color: var(--tm-color-text-secondary);
  background: transparent;
  border-color: transparent;
}

.tm-button--danger {
  color: var(--tm-color-text-primary);
  background: rgba(251, 113, 133, 0.18);
  border-color: rgba(251, 113, 133, 0.36);
}

.tm-button__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.32);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: tm-button-spin 0.8s linear infinite;
}

@keyframes tm-button-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
