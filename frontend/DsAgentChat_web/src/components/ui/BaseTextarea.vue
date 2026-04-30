<template>
  <div class="tm-textarea-field" :class="{ 'has-error': Boolean(error), 'is-disabled': disabled }">
    <label v-if="label" class="tm-textarea-field__label" :for="textareaId">
      {{ label }}
    </label>

    <textarea
      :id="textareaId"
      ref="textareaRef"
      class="tm-textarea-field__control"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      :rows="rows"
      :aria-invalid="error ? 'true' : 'false'"
      :aria-label="ariaLabel"
      @input="handleInput"
    />

    <p v-if="error || hint" class="tm-textarea-field__hint">
      {{ error || hint }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string
  label?: string
  placeholder?: string
  hint?: string
  error?: string
  disabled?: boolean
  rows?: number
  maxRows?: number
  ariaLabel?: string
}>(), {
  label: '',
  placeholder: '',
  hint: '',
  error: '',
  disabled: false,
  rows: 3,
  maxRows: 6,
  ariaLabel: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const textareaRef = ref<HTMLTextAreaElement | null>(null)
const textareaId = `tm-textarea-${Math.random().toString(36).slice(2, 9)}`

function resizeToContent() {
  const el = textareaRef.value
  if (!el) return

  const lineHeight = Number.parseFloat(window.getComputedStyle(el).lineHeight || '24')
  const maxHeight = lineHeight * props.maxRows
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
  el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
}

function handleInput(event: Event) {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
  nextTick(resizeToContent)
}

watch(() => props.modelValue, () => nextTick(resizeToContent))
onMounted(resizeToContent)

defineExpose({
  focus: () => textareaRef.value?.focus(),
})
</script>

<style scoped>
.tm-textarea-field {
  display: grid;
  gap: var(--tm-space-2);
  width: 100%;
}

.tm-textarea-field__label {
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-sm);
  font-weight: 700;
}

.tm-textarea-field__control {
  width: 100%;
  min-height: 48px;
  max-height: 220px;
  padding: var(--tm-space-3) var(--tm-space-4);
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-xl);
  background: rgba(15, 23, 42, 0.68);
  color: var(--tm-color-text-primary);
  line-height: var(--tm-line-height-normal);
  resize: none;
  transition:
    border-color var(--tm-motion-fast),
    background var(--tm-motion-fast),
    box-shadow var(--tm-motion-fast);
}

.tm-textarea-field__control::placeholder {
  color: var(--tm-color-text-muted);
}

.tm-textarea-field__control:focus {
  border-color: var(--tm-color-border-strong);
  background: rgba(15, 23, 42, 0.84);
  outline: none;
  box-shadow: var(--tm-shadow-focus);
}

.tm-textarea-field__control:disabled {
  opacity: 0.62;
}

.tm-textarea-field.has-error .tm-textarea-field__control {
  border-color: rgba(251, 113, 133, 0.5);
}

.tm-textarea-field__hint {
  margin: 0;
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-xs);
  line-height: var(--tm-line-height-normal);
}

.tm-textarea-field.has-error .tm-textarea-field__hint {
  color: var(--tm-color-danger);
}

.tm-textarea-field.is-disabled {
  opacity: 0.82;
}
</style>
