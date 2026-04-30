<template>
  <label class="tm-field">
    <span v-if="label" class="tm-field__label">{{ label }}</span>
    <span class="tm-field__control" :class="{ 'has-error': error, 'is-disabled': disabled }">
      <slot name="prefix" />
      <input
        class="tm-field__input"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :autocomplete="autocomplete"
        :aria-invalid="error ? 'true' : 'false'"
        :aria-describedby="hint || error ? descriptionId : undefined"
        @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        @blur="$emit('blur')"
      />
      <slot name="suffix" />
    </span>
    <span v-if="error || hint" :id="descriptionId" class="tm-field__message" :class="{ error: error }">
      {{ error || hint }}
    </span>
  </label>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{
  modelValue: string
  label?: string
  placeholder?: string
  type?: string
  hint?: string
  error?: string
  disabled?: boolean
  autocomplete?: string
}>(), {
  label: '',
  placeholder: '',
  type: 'text',
  hint: '',
  error: '',
  disabled: false,
  autocomplete: undefined
})

defineEmits<{
  'update:modelValue': [value: string]
  blur: []
}>()

const descriptionId = `tm-field-${Math.random().toString(36).slice(2)}`
</script>

<style scoped>
.tm-field {
  display: grid;
  gap: var(--tm-space-2);
}

.tm-field__label {
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-sm);
  font-weight: 700;
}

.tm-field__control {
  min-height: 48px;
  display: flex;
  align-items: center;
  gap: var(--tm-space-2);
  padding: 0 var(--tm-space-4);
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-lg);
  background: rgba(15, 23, 42, 0.64);
  transition:
    border-color var(--tm-motion-fast),
    box-shadow var(--tm-motion-fast),
    background var(--tm-motion-fast);
}

.tm-field__control:focus-within {
  border-color: var(--tm-color-cyan);
  box-shadow: var(--tm-shadow-focus);
  background: rgba(15, 23, 42, 0.82);
}

.tm-field__control.has-error {
  border-color: rgba(251, 113, 133, 0.72);
}

.tm-field__control.is-disabled {
  opacity: 0.58;
}

.tm-field__input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--tm-color-text-primary);
  font-size: var(--tm-font-size-md);
}

.tm-field__input::placeholder {
  color: var(--tm-color-text-muted);
}

.tm-field__message {
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-xs);
  line-height: var(--tm-line-height-normal);
}

.tm-field__message.error {
  color: var(--tm-color-danger);
}
</style>
