<template>
  <section class="trip-overview fade-in">
    <div class="ov-header">
      <svg class="ov-icon" width="20" height="20" viewBox="0 0 24 24" fill="none">
        <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" stroke="currentColor" stroke-width="1.5"/>
        <circle cx="12" cy="9" r="2.5" stroke="currentColor" stroke-width="1.5"/>
      </svg>
      <h3 class="ov-city">{{ profile.destination_city }}</h3>
    </div>
    <div class="ov-tags">
      <span
        v-if="profile.constraints?.traveler_type"
        class="tag tag-accent"
      >{{ profile.constraints.traveler_type }}</span>
      <span class="tag">{{ dayCount }} 天</span>
      <span
        v-if="profile.constraints?.budget_range"
        class="tag"
      >{{ profile.constraints.budget_range }}</span>
      <span
        v-for="pref in (profile.constraints?.preferences || [])"
        :key="pref"
        class="tag tag-warm"
      >{{ pref }}</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { TripProfile } from '../../types/itinerary'

defineProps<{
  profile: TripProfile
  dayCount: number
}>()
</script>

<style scoped>
.trip-overview {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 18px;
  margin-bottom: 16px;
}

.ov-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.ov-icon { color: var(--accent); flex-shrink: 0; }

.ov-city {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.ov-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  display: inline-flex;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 500;
  border-radius: 999px;
  background: rgba(255,255,255,0.05);
  color: var(--text-sec);
  border: 1px solid var(--border);
}

.tag-accent {
  background: var(--accent-soft);
  color: #7dd3fc;
  border-color: rgba(14, 165, 233, 0.2);
}

.tag-warm {
  background: var(--accent-warm-soft);
  color: #fde68a;
  border-color: rgba(245, 158, 11, 0.2);
}

.fade-in { animation: fadeIn 0.4s ease-out both; }

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}
</style>
