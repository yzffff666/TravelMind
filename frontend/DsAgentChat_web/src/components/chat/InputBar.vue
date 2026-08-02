<template>
  <div class="input-bar">
    <div class="input-inner">
      <div class="composer" :class="{ 'is-streaming': isStreaming }">
        <BaseTextarea
          ref="composerRef"
          v-model="text"
          :disabled="isStreaming"
          :rows="1"
          :maxRows="5"
          :aria-label="t('input.label')"
          :placeholder="t('input.placeholder')"
          @keydown.enter="onEnterKey"
        />
        <BaseButton
          class="btn-send"
          :class="{ 'is-icon-only': !sendLabel }"
          variant="primary"
          size="md"
          :disabled="isStreaming || !text.trim()"
          :loading="isStreaming"
          :aria-label="isStreaming ? t('input.generating') : t('input.send')"
          @click="handleSubmit"
        >
          <svg v-if="!isStreaming" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <line x1="22" y1="2" x2="11" y2="13"/>
            <polygon points="22 2 15 22 11 13 2 9 22 2"/>
          </svg>
          <span v-if="sendLabel">{{ sendLabel }}</span>
        </BaseButton>
      </div>
      <BaseButton
        v-if="canReset"
        class="btn-reset"
        variant="secondary"
        size="md"
        :disabled="isStreaming"
        @click="$emit('reset')"
      >
        {{ t('input.reset') }}
      </BaseButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { BaseButton, BaseTextarea } from '../ui'

const { t } = useI18n()

const props = defineProps<{
  isStreaming: boolean
  canReset: boolean
}>()

const emit = defineEmits<{
  submit: [query: string]
  reset: []
}>()

const text = ref('')
const composerRef = ref<InstanceType<typeof BaseTextarea> | null>(null)
const sendLabel = computed(() => props.isStreaming ? t('input.generating') : '')

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
    composerRef.value?.focus()
  }
})

defineExpose({ focus: () => composerRef.value?.focus() })
</script>

<style scoped>
.input-bar {
  flex-shrink: 0;
  border-top: 1px solid var(--tm-color-border);
  background: rgba(7, 8, 20, 0.76);
  padding: var(--tm-space-4) var(--tm-space-6) var(--tm-space-5);
  backdrop-filter: var(--tm-blur-glass);
}

.input-inner {
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  gap: var(--tm-space-3);
  align-items: flex-end;
}

.composer {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: var(--tm-space-3);
  min-width: 0;
}

.composer.is-streaming {
  opacity: 0.82;
}

.btn-send {
  min-width: 48px;
  flex-shrink: 0;
}

.btn-send.is-icon-only {
  width: 48px;
  padding: 0;
}

.btn-reset {
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .input-bar {
    padding: var(--tm-space-3) var(--tm-space-4) var(--tm-space-4);
  }

  .input-inner {
    align-items: stretch;
    flex-direction: column;
    gap: var(--tm-space-2);
  }

  .composer {
    align-items: flex-end;
  }

  .btn-reset {
    width: 100%;
  }
}
</style>
