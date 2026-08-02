<template>
  <div class="empty">
    <div class="empty-visual">
      <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
        <circle cx="32" cy="28" r="18" stroke="currentColor" stroke-width="1.2" opacity="0.25"/>
        <path d="M32 10v36M14 28h36" stroke="currentColor" stroke-width="1" opacity="0.12"/>
        <path d="M32 16c-5.52 0-10 4.48-10 10 0 8 10 18 10 18s10-10 10-18c0-5.52-4.48-10-10-10z" stroke="currentColor" stroke-width="1.5"/>
        <circle cx="32" cy="26" r="3" stroke="currentColor" stroke-width="1.5"/>
        <path d="M20 52h24M24 48h16" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" opacity="0.2"/>
      </svg>
    </div>
    <p class="empty-title">{{ t('emptyState.title') }}</p>
    <p class="empty-sub">{{ t('emptyState.subtitle') }}</p>

    <div class="suggestions">
      <button
        v-for="s in suggestions"
        :key="s.query"
        class="sg-card"
        @click="$emit('suggest', s.query)"
      >
        <span class="sg-emoji">{{ s.emoji }}</span>
        <span class="sg-city">{{ s.city }}</span>
        <span class="sg-desc">{{ s.desc }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

defineEmits<{
  suggest: [query: string]
}>()

const { t } = useI18n()
const suggestionKeys = ['tokyo', 'phuket', 'kyoto', 'shanghai', 'beijing', 'chiangMai'] as const
const suggestionIcons = ['TYO', 'HKT', 'KYO', 'SHA', 'BJS', 'CNX']
const suggestions = computed(() => suggestionKeys.map((key, index) => ({
  emoji: suggestionIcons[index],
  city: t(`emptyState.suggestions.${key}.city`),
  desc: t(`emptyState.suggestions.${key}.desc`),
  query: t(`emptyState.suggestions.${key}.query`),
})))
</script>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: 40px 24px;
}

.empty-visual {
  color: var(--text-muted);
  opacity: 0.35;
  margin-bottom: 24px;
}

.empty-title {
  margin: 0;
  font-size: 16px;
  font-weight: 400;
  color: var(--text-sec);
  letter-spacing: -0.01em;
}

.empty-sub {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--text-muted);
  max-width: 320px;
}

.suggestions {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-top: 28px;
  max-width: 480px;
  width: 100%;
}

.sg-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 16px 8px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.sg-card:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
}

.sg-emoji {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--tm-color-primary);
  line-height: 1;
}

.sg-city {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.sg-desc {
  font-size: 11px;
  color: var(--text-muted);
}

@media (max-width: 480px) {
  .suggestions {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
