<template>
  <div class="input-bar">
    <div class="input-inner">
      <div class="textarea-wrap" :class="{ focused, disabled: isStreaming }">
        <textarea
          ref="textareaRef"
          v-model="text"
          :disabled="isStreaming"
          rows="1"
          placeholder="输入你的想法…"
          @focus="focused = true"
          @blur="focused = false"
          @keydown.enter="onEnterKey"
        />
        <button
          class="btn-send"
          :disabled="isStreaming || !text.trim()"
          @click="handleSubmit"
        >
          <svg v-if="isStreaming" class="spinner" width="16" height="16" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="32" stroke-dashoffset="10" stroke-linecap="round"/>
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"/>
            <polygon points="22 2 15 22 11 13 2 9 22 2"/>
          </svg>
        </button>
      </div>
      <button
        v-if="canReset"
        class="btn-reset"
        :disabled="isStreaming"
        @click="$emit('reset')"
      >重置</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  isStreaming: boolean
  canReset: boolean
}>()

const emit = defineEmits<{
  submit: [query: string]
  reset: []
}>()

const text = ref('')
const focused = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const onEnterKey = (e: KeyboardEvent) => {
  if (e.shiftKey) return
  e.preventDefault()
  handleSubmit()
}

const handleSubmit = () => {
  const q = text.value.trim()
  if (!q || props.isStreaming) return
  emit('submit', q)
  text.value = ''
}

watch(() => props.isStreaming, (streaming) => {
  if (!streaming) {
    textareaRef.value?.focus()
  }
})

defineExpose({ focus: () => textareaRef.value?.focus() })
</script>

<style scoped>
.input-bar {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  background: var(--bg);
  padding: 16px 28px 20px;
}

.input-inner {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  gap: 10px;
  align-items: center;
}

.textarea-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 24px;
  background: var(--bg-card);
  padding-right: 6px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.textarea-wrap.focused {
  border-color: var(--border-hover);
  box-shadow: 0 0 0 3px rgba(255,255,255,0.02);
}

.textarea-wrap.disabled { opacity: 0.5; }

textarea {
  flex: 1;
  display: block;
  border: none;
  background: transparent;
  color: var(--text);
  padding: 12px 20px;
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  border-radius: 24px;
  font-family: inherit;
  min-height: 20px;
  max-height: 120px;
}

textarea:focus { outline: none; }
textarea::placeholder { color: var(--text-muted); }

.btn-send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  font-family: inherit;
  color: var(--text-sec);
  background: transparent;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-send:hover:not(:disabled) {
  color: var(--text);
  background: rgba(255,255,255,0.06);
}

.btn-send:active:not(:disabled) { transform: scale(0.92); }
.btn-send:disabled { opacity: 0.25; cursor: not-allowed; }

.btn-reset {
  padding: 10px 16px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.btn-reset:hover:not(:disabled) {
  color: var(--text-sec);
  border-color: var(--border-hover);
}

.btn-reset:disabled { opacity: 0.3; cursor: not-allowed; }

.spinner { animation: spin 0.8s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 768px) {
  .input-bar { padding: 12px 16px 16px; }
  .input-inner { gap: 8px; }
}
</style>
