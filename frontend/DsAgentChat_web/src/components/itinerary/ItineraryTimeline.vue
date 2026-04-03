<template>
  <div class="itinerary">
    <div
      v-for="(day, dayIdx) in days"
      :key="day.day_index"
      class="day-section slide-up"
      :style="{ animationDelay: `${dayIdx * 0.12}s` }"
    >
      <div class="day-hdr">
        <span class="day-num">第 {{ day.day_index }} 天</span>
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

          <div class="pc">
            <span class="pc-slot">{{ slot.slot }}</span>
            <h4 class="pc-activity">{{ slot.activity }}</h4>

            <div v-if="slot.place" class="pc-row">
              <svg class="pc-ico" width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" stroke="currentColor" stroke-width="1.5"/>
                <circle cx="12" cy="9" r="2" stroke="currentColor" stroke-width="1.5"/>
              </svg>
              <span>{{ slot.place }}</span>
            </div>

            <div v-if="slot.transit" class="pc-row pc-transit">
              <svg class="pc-ico" width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M13 17l5-5-5-5M6 17l5-5-5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span>{{ slot.transit }}</span>
            </div>

            <span v-if="slotCost(slot)" class="pc-cost">
              &yen;{{ fmt(slotCost(slot)!) }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ItineraryDay, ItinerarySlot } from '../../types/itinerary'

defineProps<{ days: ItineraryDay[] }>()

const fmt = (n: number) => Math.round(n).toLocaleString('zh-CN')

const slotCost = (slot: ItinerarySlot): number | null => {
  const cb = slot.cost_breakdown
  if (!cb) return null
  const sum = (cb.transport || 0) + (cb.hotel || 0) + (cb.tickets || 0) + (cb.food || 0) + (cb.other || 0)
  return sum > 0 ? sum : null
}
</script>

<style scoped>
.itinerary { max-width: 680px; }

.day-section { margin-bottom: 44px; }
.day-section:last-child { margin-bottom: 0; }

.day-hdr {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 22px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.day-num {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  padding: 4px 14px;
  background: var(--accent-soft);
  border-radius: 999px;
  letter-spacing: 0.03em;
}

.day-theme {
  font-size: 14px;
  font-weight: 400;
  color: var(--text-sec);
  font-style: italic;
}

.timeline {
  position: relative;
  padding-left: 32px;
}

.tl-item {
  position: relative;
  padding-bottom: 22px;
}

.tl-item:last-child { padding-bottom: 0; }

.tl-rail {
  position: absolute;
  left: -32px;
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
  background: var(--bg-deep);
  border: 2px solid var(--accent);
  flex-shrink: 0;
  z-index: 1;
  margin-top: 8px;
}

.tl-line {
  width: 1px;
  flex: 1;
  background: var(--border);
  margin-top: 4px;
}

.pc {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 16px 20px;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
}

.pc:hover {
  border-color: var(--border-hover);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
  transform: translateY(-2px);
}

.pc-slot {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 6px;
}

.pc-activity {
  margin: 0 0 10px;
  font-size: 15px;
  font-weight: 500;
  line-height: 1.45;
  color: var(--text);
}

.pc-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 12.5px;
  color: var(--text-sec);
  line-height: 1.5;
}

.pc-row:last-of-type { margin-bottom: 0; }

.pc-ico {
  flex-shrink: 0;
  margin-top: 1px;
  color: var(--text-muted);
}

.pc-transit {
  color: var(--text-muted);
  font-size: 11.5px;
}

.pc-cost {
  display: inline-flex;
  margin-top: 10px;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 500;
  color: var(--accent-warm);
  background: var(--accent-warm-soft);
  border-radius: var(--r-sm);
  letter-spacing: 0.01em;
}

.slide-up { animation: slideUp 0.5s ease-out both; }

@keyframes slideUp {
  from { opacity: 0; transform: translateY(18px); }
  to   { opacity: 1; transform: translateY(0); }
}

@media (max-width: 480px) {
  .timeline { padding-left: 24px; }
  .tl-rail  { left: -24px; }
  .pc { padding: 14px 16px; }
  .day-hdr { gap: 10px; margin-bottom: 16px; padding-bottom: 10px; }
}
</style>
