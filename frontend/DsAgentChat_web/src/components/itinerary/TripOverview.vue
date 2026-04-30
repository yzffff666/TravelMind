<template>
  <GlassCard class="trip-overview fade-in">
    <div class="ov-header">
      <div class="ov-icon-wrap" aria-hidden="true">
        <svg class="ov-icon" width="20" height="20" viewBox="0 0 24 24" fill="none">
          <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" stroke="currentColor" stroke-width="1.5"/>
          <circle cx="12" cy="9" r="2.5" stroke="currentColor" stroke-width="1.5"/>
        </svg>
      </div>
      <div class="ov-title">
        <span class="ov-kicker">Trip overview</span>
        <h3 class="ov-city">{{ profile.destination_city }}</h3>
      </div>
    </div>
    <div class="ov-tags">
      <StatusBadge
        v-if="profile.constraints?.traveler_type"
        tone="info"
      >{{ profile.constraints.traveler_type }}</StatusBadge>
      <StatusBadge tone="success">{{ dayCount }} 天</StatusBadge>
      <StatusBadge
        v-if="profile.constraints?.budget_range"
        tone="neutral"
      >{{ profile.constraints.budget_range }}</StatusBadge>
      <span
        v-for="pref in (profile.constraints?.preferences || [])"
        :key="pref"
        class="pref-chip"
      >{{ pref }}</span>
    </div>
  </GlassCard>
</template>

<script setup lang="ts">
import type { TripProfile } from '../../types/itinerary'
import { GlassCard, StatusBadge } from '../ui'

defineProps<{
  profile: TripProfile
  dayCount: number
}>()
</script>

<style scoped>
.trip-overview {
  padding: var(--tm-space-5);
  margin-bottom: 16px;
}

.ov-header {
  display: flex;
  align-items: center;
  gap: var(--tm-space-3);
  margin-bottom: var(--tm-space-4);
}

.ov-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-lg);
  background: var(--tm-color-primary-soft);
  color: var(--tm-color-cyan);
}

.ov-icon { flex-shrink: 0; }

.ov-title {
  min-width: 0;
}

.ov-kicker {
  display: block;
  margin-bottom: var(--tm-space-1);
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-xs);
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.ov-city {
  margin: 0;
  color: var(--tm-color-text-primary);
  font-size: var(--tm-font-size-xl);
  font-weight: 800;
  letter-spacing: -0.01em;
  line-height: var(--tm-line-height-tight);
}

.ov-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--tm-space-2);
}

.pref-chip {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 var(--tm-space-3);
  border: 1px solid rgba(251, 191, 36, 0.28);
  border-radius: var(--tm-radius-pill);
  background: rgba(251, 191, 36, 0.1);
  color: var(--tm-color-warning);
  font-size: var(--tm-font-size-xs);
  font-weight: 700;
}

.fade-in { animation: fadeIn 0.4s ease-out both; }

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}
</style>
