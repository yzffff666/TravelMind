<template>
  <div class="itinerary">
    <div
      v-for="(day, dayIdx) in days"
      :key="day.day_index"
      :ref="(el) => { if (el) dayRefs[day.day_index] = el as HTMLElement }"
      class="day-section slide-up"
      :class="{ 'day-changed': changedDays?.includes(day.day_index) }"
      :style="{ animationDelay: `${dayIdx * 0.12}s` }"
    >
      <div class="day-hdr">
        <StatusBadge :tone="changedDays?.includes(day.day_index) ? 'success' : 'info'">
          {{ t('common.day', { day: day.day_index }) }}
        </StatusBadge>
        <span v-if="day.theme" class="day-theme">{{ day.theme }}</span>
      </div>

      <div class="timeline">
        <div
          v-for="(slot, si) in day.slots"
          :key="`${day.day_index}-${si}`"
          class="tl-item slide-up"
          :style="{ animationDelay: `${dayIdx * 0.12 + si * 0.06 + 0.08}s` }"
        >
          <div class="tl-rail">
            <span class="tl-dot" />
            <span v-if="si < day.slots.length - 1" class="tl-line" />
          </div>

          <GlassCard interactive class="pc" :class="{ 'pc-with-img': slot.image_url }">
            <img
              v-if="slot.image_url"
              :src="slot.image_url"
              :alt="slot.place || slot.activity"
              class="pc-img"
              loading="lazy"
              @error="($event.target as HTMLImageElement).style.display = 'none'"
            />
            <div class="pc-body">
              <div class="pc-topline">
                <StatusBadge tone="neutral">{{ slot.slot }}</StatusBadge>
                <StatusBadge v-if="slot.location" tone="info">{{ t('timeline.located') }}</StatusBadge>
              </div>

              <h4 class="pc-activity">{{ slot.activity }}</h4>

              <div v-if="slot.place" class="pc-place">
                <svg class="pc-ico" width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" stroke="currentColor" stroke-width="1.5"/>
                  <circle cx="12" cy="9" r="2" stroke="currentColor" stroke-width="1.5"/>
                </svg>
                <span>{{ slot.place }}</span>
              </div>

              <div v-if="slot.transit" class="pc-row pc-transit">
                <svg class="pc-ico" width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M13 17l5-5-5-5M6 17l5-5-5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>{{ slot.transit }}</span>
              </div>

              <div class="pc-bottom">
                <StatusBadge v-if="slotCost(slot)" class="pc-cost" tone="warning">
                  &yen;{{ fmt(slotCost(slot)!) }}
                </StatusBadge>
                <StatusBadge v-if="slot.transit" tone="neutral">
                  {{ t('timeline.transport') }}
                </StatusBadge>
                <StatusBadge
                  v-if="slot.evidence_refs && slot.evidence_refs.length > 0"
                  class="pc-evidence"
                  tone="success"
                  :title="t('timeline.evidenceTitle', { count: slot.evidence_refs.length })"
                >
                  {{ t('timeline.verified', { count: slot.evidence_refs.length }) }}
                </StatusBadge>
              </div>
            </div><!-- /.pc-body -->
          </GlassCard>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ItineraryDay, ItinerarySlot } from '../../types/itinerary'
import { GlassCard, StatusBadge } from '../ui'

const props = defineProps<{
  days: ItineraryDay[]
  changedDays?: number[]
}>()
const { n, t } = useI18n()

const dayRefs = ref<Record<number, HTMLElement>>({})

defineExpose({ scrollToDay })

function scrollToDay(dayIndex: number) {
  nextTick(() => {
    const el = dayRefs.value[dayIndex]
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

const fmt = (value: number) => n(Math.round(value), 'integer')

const slotCost = (slot: ItinerarySlot): number | null => {
  const cb = slot.cost_breakdown
  if (!cb) return null
  const sum = (cb.transport || 0) + (cb.hotel || 0) + (cb.tickets || 0) + (cb.food || 0) + (cb.other || 0)
  return sum > 0 ? sum : null
}
</script>

<style scoped>
.itinerary { max-width: 700px; }

.day-section { margin-bottom: var(--tm-space-10); }
.day-section:last-child { margin-bottom: var(--tm-space-6); }

.day-hdr {
  display: flex;
  align-items: center;
  gap: var(--tm-space-3);
  margin-bottom: var(--tm-space-5);
  padding-bottom: var(--tm-space-4);
  border-bottom: 1px solid var(--tm-color-border);
}

.day-theme {
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-sm);
  font-weight: 500;
  font-style: italic;
}

.timeline {
  position: relative;
  padding-left: var(--tm-space-8);
}

.tl-item {
  position: relative;
  padding-bottom: var(--tm-space-6);
}

.tl-item:last-child { padding-bottom: 0; }

.tl-rail {
  position: absolute;
  left: calc(var(--tm-space-8) * -1);
  top: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  width: 12px;
}

.tl-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--tm-color-bg);
  border: 2px solid var(--tm-color-cyan);
  box-shadow: 0 0 18px rgba(216, 192, 138, 0.34);
  flex-shrink: 0;
  z-index: 1;
  margin-top: var(--tm-space-4);
}

.tl-line {
  width: 1px;
  flex: 1;
  background: linear-gradient(180deg, var(--tm-color-border-strong), transparent);
  margin-top: var(--tm-space-1);
}

.pc {
  position: relative;
  padding: var(--tm-space-6);
  overflow: hidden;
}

.pc::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(247, 242, 232, 0.035), transparent 42%),
    radial-gradient(circle at 92% 10%, rgba(198, 161, 91, 0.13), transparent 34%);
  opacity: 0.9;
  pointer-events: none;
}

.pc-with-img {
  display: flex;
  gap: 0;
  padding: 0;
}

.pc-with-img .pc-body {
  padding: var(--tm-space-6);
  flex: 1;
  min-width: 0;
}

.pc-body {
  position: relative;
  z-index: 1;
}

.pc:not(.pc-with-img) .pc-body {
  /* no extra styling needed when no image */
}

.pc-img {
  width: 168px;
  min-height: 100%;
  object-fit: cover;
  flex-shrink: 0;
  border-radius: var(--tm-radius-2xl) 0 0 var(--tm-radius-2xl);
  filter: saturate(0.9) contrast(1.05);
}

.pc:hover {
  border-color: var(--tm-color-border-strong);
}

.pc-topline {
  display: flex;
  flex-wrap: wrap;
  gap: var(--tm-space-2);
  margin-bottom: var(--tm-space-4);
}

.pc-activity {
  margin: 0 0 var(--tm-space-4);
  color: var(--tm-color-text-primary);
  font-size: clamp(var(--tm-font-size-md), 2.5vw, var(--tm-font-size-xl));
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.25;
}

.pc-place {
  display: flex;
  align-items: flex-start;
  gap: var(--tm-space-2);
  margin-bottom: var(--tm-space-3);
  color: var(--tm-color-primary-hover);
  font-size: var(--tm-font-size-sm);
  font-weight: 800;
  line-height: var(--tm-line-height-normal);
}

.pc-row {
  display: flex;
  align-items: flex-start;
  gap: var(--tm-space-2);
  margin-bottom: var(--tm-space-2);
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-sm);
  line-height: var(--tm-line-height-normal);
}

.pc-row:last-of-type { margin-bottom: 0; }

.pc-ico {
  flex-shrink: 0;
  margin-top: 3px;
  color: var(--tm-color-text-muted);
}

.pc-transit {
  color: var(--tm-color-text-muted);
  font-size: var(--tm-font-size-xs);
}

.pc-bottom {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--tm-space-2);
  margin-top: var(--tm-space-5);
  padding-top: var(--tm-space-4);
  border-top: 1px solid var(--tm-color-border);
}

/* ---- Changed-day highlight ---- */

.day-changed {
  animation: dayGlow 3s ease-out both;
}

.day-changed .pc {
  border-color: rgba(52, 211, 153, 0.34);
  box-shadow: var(--tm-shadow-card), 0 0 24px rgba(52, 211, 153, 0.12);
}

@keyframes dayGlow {
  0%   { background: rgba(52, 211, 153, 0.08); border-radius: var(--tm-radius-xl); }
  100% { background: transparent; }
}

.slide-up { animation: slideUp 0.5s ease-out both; }

@keyframes slideUp {
  from { opacity: 0; transform: translateY(18px); }
  to   { opacity: 1; transform: translateY(0); }
}

@media (max-width: 480px) {
  .timeline { padding-left: var(--tm-space-6); }
  .tl-rail  { left: calc(var(--tm-space-6) * -1); }
  .pc { padding: var(--tm-space-4); }
  .pc-with-img { flex-direction: column; }
  .pc-with-img .pc-body { padding: var(--tm-space-4); }
  .pc-img {
    width: 100%;
    max-height: 220px;
    border-radius: var(--tm-radius-2xl) var(--tm-radius-2xl) 0 0;
  }
  .day-hdr { gap: var(--tm-space-2); margin-bottom: var(--tm-space-4); padding-bottom: var(--tm-space-3); }
}
</style>
