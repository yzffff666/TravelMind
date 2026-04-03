<template>
  <div class="input-bar">
    <div class="input-inner">
      <div class="textarea-wrap" :class="{ focused, disabled: isStreaming }">
        <textarea
          ref="textareaRef"
          v-model="text"
          :disabled="isStreaming"
          rows="2"
          placeholder="描述你的旅行需求，或对当前行程提出修改…"
          @focus="focused = true"
          @blur="focused = false"
          @keydown.enter.ctrl.prevent="handleSubmit"
        />
      </div>
      <div class="bar-actions">
        <button
          class="btn-send"
          :disabled="isStreaming || !text.trim()"
          @click="handleSubmit"
        >
          <svg v-if="isStreaming" class="spinner" width="14" height="14" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="32" stroke-dashoffset="10" stroke-linecap="round"/>
          </svg>
          {{ isStreaming ? '处理中…' : '发送' }}
        </button>
        <button
          v-if="canReset"
          class="btn-reset"
          :disabled="isStreaming"
          @click="$emit('reset')"
        >重置</button>
      </div>
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
  padding: 12px 20px 14px;
}

.input-inner {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.textarea-wrap {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--bg-deep);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.textarea-wrap.focused {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.textarea-wrap.disabled { opacity: 0.5; }

textarea {
  display: block;
  width: 100%;
  border: none;
  background: transparent;
  color: var(--text);
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.6;
  resize: none;
  border-radius: var(--r-md);
  font-family: inherit;
}

textarea:focus { outline: none; }
textarea::placeholder { color: var(--text-muted); }

.bar-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.btn-send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 18px;
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  color: #fff;
  background: var(--accent);
  border: none;
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.btn-send:hover:not(:disabled) {
  background: #0284c7;
  box-shadow: 0 4px 20px rgba(14, 165, 233, 0.28);
}

.btn-send:active:not(:disabled) { transform: scale(0.98); }
.btn-send:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-reset {
  padding: 9px 14px;
  font-size: 11px;
  font-weight: 500;
  font-family: inherit;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.btn-reset:hover:not(:disabled) {
  color: var(--text-sec);
  border-color: var(--border-hover);
}

.btn-reset:disabled { opacity: 0.4; cursor: not-allowed; }

.spinner { animation: spin 0.8s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 768px) {
  .input-bar { padding: 10px 12px 12px; }
  .input-inner { gap: 8px; }
}
</style>
