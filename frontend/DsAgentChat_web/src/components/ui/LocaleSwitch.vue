<template>
  <div class="locale-switch" role="group" :aria-label="t('localeSwitch.label')">
    <button
      v-for="option in options"
      :key="option.locale"
      type="button"
      class="locale-switch__option"
      :class="{ 'is-active': locale === option.locale }"
      :data-locale="option.locale"
      :aria-pressed="locale === option.locale"
      :title="t(option.titleKey)"
      @click="setAppLocale(option.locale)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { setAppLocale, type AppLocale } from '../../i18n'

const { locale, t } = useI18n()

const options: Array<{ locale: AppLocale; label: string; titleKey: string }> = [
  { locale: 'en', label: 'EN', titleKey: 'localeSwitch.english' },
  { locale: 'zh-CN', label: '中文', titleKey: 'localeSwitch.chinese' },
]
</script>

<style scoped>
.locale-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(42px, 1fr));
  min-width: 96px;
  height: 34px;
  padding: 3px;
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-sm);
  background: rgba(10, 10, 9, 0.66);
}

.locale-switch__option {
  min-width: 42px;
  padding: 0 var(--tm-space-2);
  border: 0;
  border-radius: 5px;
  color: var(--tm-color-text-muted);
  background: transparent;
  font-size: var(--tm-font-size-xs);
  font-weight: 700;
  line-height: 1;
  transition:
    color var(--tm-motion-fast),
    background var(--tm-motion-fast);
}

.locale-switch__option:hover {
  color: var(--tm-color-text-primary);
}

.locale-switch__option.is-active {
  color: var(--tm-color-text-inverse);
  background: var(--tm-color-primary);
}

.locale-switch__option:focus-visible {
  outline-offset: 1px;
}
</style>
