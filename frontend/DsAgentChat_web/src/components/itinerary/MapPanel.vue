<template>
  <div class="map-panel">
    <div ref="mapContainer" class="map-container" />
    <div v-if="!mapReady" class="map-placeholder map-placeholder--fullscreen">
      <div class="map-placeholder-card" :class="{ 'map-placeholder-card--error': mapError }">
        <StatusBadge :tone="mapError ? 'danger' : 'info'">
          {{ mapError ? t('map.statusError') : t('map.statusLoading') }}
        </StatusBadge>
        <div class="map-placeholder-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="M9 18 3 21V6l6-3 6 3 6-3v15l-6 3-6-3Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
            <path d="M9 3v15M15 6v15" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
          </svg>
        </div>
        <div>
          <p class="map-placeholder-title">{{ mapError ? t('map.titleError') : t('map.titleLoading') }}</p>
          <p class="map-placeholder-desc">
            {{ mapError || t('map.description') }}
          </p>
        </div>
      </div>
    </div>
    <div v-if="mapReady" class="map-engine-chip">
      <StatusBadge :tone="mapEngine === 'leaflet' ? 'info' : 'success'">
        {{ mapEngineLabel }}
      </StatusBadge>
      <span class="map-engine-count">{{ t('map.pointCount', { active: activeLocationCount, total: totalLocationCount }) }}</span>
    </div>
    <div
      v-if="mapReady && slotsWithLocation.length === 0 && dayTabs.length > 0"
      class="map-hint"
    >
      <StatusBadge tone="warning">{{ t('map.noPoints') }}</StatusBadge>
      <span class="map-hint-title">{{ t('map.switchDay') }}</span>
      <span class="map-hint-sub">{{ t('map.keyHint') }}</span>
    </div>
    <div v-if="mapReady && dayTabs.length > 0" class="day-tabs">
      <button
        v-for="tab in dayTabs"
        :key="tab.index"
        :class="['day-tab', { active: tab.index === activeDayIndex }]"
        :aria-pressed="tab.index === activeDayIndex"
        :title="tab.theme || t('common.day', { day: tab.index })"
        @click="$emit('selectDay', tab.index)"
      >
        {{ t('common.day', { day: tab.index }) }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ItineraryDay, ItinerarySlot, Location } from '@/types/itinerary'
import AMapLoader from '@amap/amap-jsapi-loader'
import { StatusBadge } from '../ui'

const props = defineProps<{
  days: ItineraryDay[]
  activeDayIndex: number
  activeSlotIndex?: number
  visible?: boolean
}>()

const emit = defineEmits<{
  selectDay: [dayIndex: number]
  selectSlot: [dayIndex: number, slotIndex: number]
}>()
const { t } = useI18n()

const mapContainer = ref<HTMLElement>()
const mapReady = ref(false)
const mapError = ref('')
const mapEngine = ref<'amap' | 'leaflet'>('amap')

let mapInstance: any = null
let AMapLib: any = null
let markers: any[] = []
let polyline: any = null
let infoWindow: any = null
let leafletLib: any = null
let leafletMarkers: any[] = []
let leafletPolyline: any = null
let leafletMarkerBySlot = new Map<number, any>()
let _mapLoading = false

const SLOT_COLORS: Record<string, string> = {
  '上午': '#c6a15b',
  '下午': '#8f7a55',
  '晚上': '#5f5441',
}
const DEFAULT_COLOR = '#9fbe9b'

const dayTabs = computed(() =>
  props.days.map(d => ({ index: d.day_index, theme: d.theme }))
)
const mapEngineLabel = computed(() =>
  mapEngine.value === 'leaflet' ? t('map.engineOverseas') : t('map.engineChina')
)
const activeLocationCount = computed(() => slotsWithLocation.value.length)
const totalLocationCount = computed(() => allLocations.value.length)

const activeDay = computed(() =>
  props.days.find(d => d.day_index === props.activeDayIndex) ?? props.days[0]
)

const allLocations = computed((): Location[] => {
  return props.days
    .flatMap(day => day.slots)
    .filter((s) => s.location != null)
    .map((s) => s.location as Location)
})

const slotsWithLocation = computed((): { slot: ItinerarySlot; idx: number; loc: Location }[] => {
  if (!activeDay.value) return []
  return activeDay.value.slots
    .filter((s) => s.location != null)
    .map((s, i) => ({ slot: s, idx: i, loc: s.location as Location }))
})

function isChinaPoint(lat: number, lng: number): boolean {
  // Coarse China mainland-ish bounds:
  // use lat>=18 to avoid Thailand/SEA points (e.g. Phuket ~7.9N) being misclassified as China.
  return lng >= 73 && lng <= 136 && lat >= 18 && lat <= 54
}

const OVERSEAS_HINTS = [
  '普吉', '泰国', 'phuket', 'thailand', 'bangkok',
  '东京', '大阪', '京都', '首尔', '新加坡',
  'tokyo', 'osaka', 'kyoto', 'seoul', 'singapore',
  'paris', 'london', 'rome',
]

function hasOverseasTextHint(): boolean {
  const text = props.days
    .flatMap(day => day.slots)
    .map(slot => `${slot.place || ''} ${slot.activity || ''}`.toLowerCase())
    .join(' ')
  return OVERSEAS_HINTS.some(h => text.includes(h.toLowerCase()))
}

function chooseEngine(): 'amap' | 'leaflet' {
  if (allLocations.value.length === 0) return 'amap'
  if (hasOverseasTextHint()) return 'leaflet'
  const hasOverseas = allLocations.value.some(loc => !isChinaPoint(loc.lat, loc.lng))
  return hasOverseas ? 'leaflet' : 'amap'
}

async function loadLeaflet(): Promise<any> {
  if ((window as any).L) return (window as any).L

  const existingCss = document.getElementById('leaflet-css')
  if (!existingCss) {
    const css = document.createElement('link')
    css.id = 'leaflet-css'
    css.rel = 'stylesheet'
    css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
    document.head.appendChild(css)
  }

  if (!(window as any).__leafletLoadingPromise) {
    ;(window as any).__leafletLoadingPromise = new Promise<void>((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('Leaflet script load failed'))
      document.head.appendChild(script)
    })
  }
  await (window as any).__leafletLoadingPromise
  return (window as any).L
}

function clearAmapLayers() {
  if (markers.length) {
    mapInstance?.remove(markers)
    markers = []
  }
  if (polyline) {
    mapInstance?.remove(polyline)
    polyline = null
  }
  infoWindow?.close()
}

function clearLeafletLayers() {
  leafletMarkers.forEach(m => m.remove())
  leafletMarkers = []
  leafletMarkerBySlot.clear()
  if (leafletPolyline) {
    leafletPolyline.remove()
    leafletPolyline = null
  }
}

function destroyMapInstance() {
  if (!mapInstance) return
  if (mapEngine.value === 'amap') {
    clearAmapLayers()
    mapInstance.destroy?.()
    AMapLib = null
    infoWindow = null
  } else {
    clearLeafletLayers()
    mapInstance.remove?.()
  }
  mapInstance = null
}

async function initAmap() {
  if (_mapLoading || mapInstance) return
  const key = import.meta.env.VITE_AMAP_KEY
  if (!key) {
    mapError.value = t('map.missingKey')
    return
  }

  _mapLoading = true
  try {
    const securityCode = import.meta.env.VITE_AMAP_SECURITY_CODE
    if (securityCode) {
      ;(window as any)._AMapSecurityConfig = { securityJsCode: securityCode }
    }

    AMapLib = await AMapLoader.load({ key, version: '2.0' })

    // 异步加载期间组件可能已卸载
    if (!mapContainer.value) return

    mapInstance = new AMapLib.Map(mapContainer.value, {
      zoom: 12,
      viewMode: '2D',
      mapStyle: 'amap://styles/whitesmoke',
    })

    infoWindow = new AMapLib.InfoWindow({ offset: new AMapLib.Pixel(0, -30) })
    mapReady.value = true
    mapError.value = ''

    await nextTick()
    renderAmapMarkers()
  } catch (e: any) {
    mapError.value = t('map.loadFailed', { error: e.message || e })
    mapReady.value = false
  } finally {
    _mapLoading = false
  }
}

async function initLeaflet() {
  if (_mapLoading || mapInstance) return
  if (!mapContainer.value) return

  _mapLoading = true
  try {
    leafletLib = await loadLeaflet()
    if (!mapContainer.value) return

    mapInstance = leafletLib.map(mapContainer.value, {
      zoomControl: true,
      attributionControl: true,
    }).setView([39.9, 116.4], 5)

    leafletLib.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(mapInstance)

    mapReady.value = true
    mapError.value = ''
    await nextTick()
    mapInstance.invalidateSize?.()
    renderLeafletMarkers()
  } catch (e: any) {
    mapError.value = t('map.overseasLoadFailed', { error: e.message || e })
    mapReady.value = false
  } finally {
    _mapLoading = false
  }
}

async function ensureMapReady() {
  const target = chooseEngine()
  if (target !== mapEngine.value) {
    destroyMapInstance()
    mapReady.value = false
    mapEngine.value = target
  }
  if (mapInstance) return
  if (mapEngine.value === 'amap') {
    await initAmap()
  } else {
    await initLeaflet()
  }
}

async function refreshMap() {
  try {
    await ensureMapReady()
    renderCurrentEngine()
  } catch (e: any) {
    mapError.value = t('map.refreshFailed', { error: e?.message || e })
    mapReady.value = false
  }
}

function renderAmapMarkers() {
  if (!mapInstance || !AMapLib) return
  clearAmapLayers()

  const items = slotsWithLocation.value
  if (items.length === 0) return

  const positions: [number, number][] = []

  items.forEach(({ slot, idx, loc }, seqIdx) => {
    const pos: [number, number] = [loc.lng, loc.lat]
    positions.push(pos)

    const color = SLOT_COLORS[slot.slot] || DEFAULT_COLOR
    const label = `${seqIdx + 1}`

    const marker = new AMapLib.Marker({
      position: pos,
      title: slot.place || slot.activity,
      label: {
        content: `<span style="
          background:${color};
          color:#fff;
          border-radius:50%;
          width:24px;height:24px;
          display:inline-flex;align-items:center;justify-content:center;
          font-size:12px;font-weight:700;
          box-shadow:0 2px 6px rgba(0,0,0,.3);
        ">${label}</span>`,
        direction: 'center',
      },
      offset: new AMapLib.Pixel(-12, -12),
      content: ' ',
    })

    marker.on('click', () => {
      emit('selectSlot', props.activeDayIndex, idx)
      const content = `
        <div style="padding:8px;max-width:200px;">
          <strong>${slot.place || slot.activity}</strong>
          <div style="color:#666;font-size:12px;margin-top:4px;">${slot.slot} · ${slot.activity}</div>
          ${slot.transit ? `<div style="color:#999;font-size:11px;margin-top:2px;">🚗 ${slot.transit}</div>` : ''}
        </div>
      `
      infoWindow.setContent(content)
      infoWindow.open(mapInstance, pos)
    })

    markers.push(marker)
  })

  mapInstance.add(markers)

  if (positions.length >= 2) {
    polyline = new AMapLib.Polyline({
      path: positions,
      strokeColor: '#c6a15b',
      strokeWeight: 3,
      strokeOpacity: 0.7,
      strokeStyle: 'dashed',
      lineJoin: 'round',
    })
    mapInstance.add(polyline)
  }

  mapInstance.setFitView(markers, false, [60, 60, 60, 60])
}

function renderLeafletMarkers() {
  if (!mapInstance || !leafletLib) return
  clearLeafletLayers()

  const items = slotsWithLocation.value
  if (items.length === 0) return

  const latLngs: [number, number][] = []

  items.forEach(({ slot, idx, loc }, seqIdx) => {
    const color = SLOT_COLORS[slot.slot] || DEFAULT_COLOR
    const label = `${seqIdx + 1}`
    const latLng: [number, number] = [loc.lat, loc.lng]
    latLngs.push(latLng)

    const icon = leafletLib.divIcon({
      className: 'leaflet-number-icon',
      html: `<span style="
        background:${color};
        color:#fff;
        border-radius:50%;
        width:24px;height:24px;
        display:inline-flex;align-items:center;justify-content:center;
        font-size:12px;font-weight:700;
        box-shadow:0 2px 6px rgba(0,0,0,.3);
      ">${label}</span>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    })

    const marker = leafletLib.marker(latLng, { icon }).addTo(mapInstance)
    const popup = `
      <div style="padding:6px;max-width:220px;">
        <strong>${slot.place || slot.activity}</strong>
        <div style="color:#666;font-size:12px;margin-top:4px;">${slot.slot} · ${slot.activity}</div>
        ${slot.transit ? `<div style="color:#999;font-size:11px;margin-top:2px;">Transit: ${slot.transit}</div>` : ''}
      </div>
    `
    marker.bindPopup(popup)
    marker.on('click', () => {
      emit('selectSlot', props.activeDayIndex, idx)
    })

    leafletMarkerBySlot.set(idx, marker)
    leafletMarkers.push(marker)
  })

  if (latLngs.length >= 2) {
    leafletPolyline = leafletLib.polyline(latLngs, {
      color: '#c6a15b',
      weight: 3,
      opacity: 0.7,
      dashArray: '8, 6',
      lineJoin: 'round',
    }).addTo(mapInstance)
  }

  const bounds = leafletLib.latLngBounds(latLngs)
  mapInstance.invalidateSize?.()
  mapInstance.fitBounds(bounds, { padding: [48, 48] })
}

function renderCurrentEngine() {
  if (mapEngine.value === 'amap') {
    renderAmapMarkers()
    return
  }
  renderLeafletMarkers()
}

function highlightSlot(slotIdx: number) {
  const item = slotsWithLocation.value.find(s => s.idx === slotIdx)
  if (!item) return
  if (mapEngine.value === 'amap') {
    if (!infoWindow || !mapInstance) return
    const pos: [number, number] = [item.loc.lng, item.loc.lat]
    mapInstance.setCenter(pos)
    mapInstance.setZoom(15)
    const content = `
      <div style="padding:8px;max-width:200px;">
        <strong>${item.slot.place || item.slot.activity}</strong>
        <div style="color:#666;font-size:12px;margin-top:4px;">${item.slot.slot} · ${item.slot.activity}</div>
      </div>
    `
    infoWindow.setContent(content)
    infoWindow.open(mapInstance, pos)
    return
  }
  const marker = leafletMarkerBySlot.get(slotIdx)
  if (!marker || !mapInstance) return
  mapInstance.setView(marker.getLatLng(), 15, { animate: true })
  marker.openPopup()
}

watch(() => props.activeDayIndex, () => {
  refreshMap()
})

watch(() => props.activeSlotIndex, (val) => {
  if (val != null) highlightSlot(val)
})

watch(
  () => props.days.map(d => `${d.day_index}:${d.slots.filter(s => s.location).length}`).join(','),
  () => { refreshMap() }
)

watch(() => props.visible, async (visible) => {
  if (!visible) return
  await nextTick()
  mapInstance?.invalidateSize?.()
  renderCurrentEngine()
})

onMounted(() => {
  refreshMap()
})

onBeforeUnmount(() => {
  destroyMapInstance()
  leafletLib = null
})

defineExpose({ highlightSlot })
</script>

<style scoped>
.map-panel {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 280px;
  border-radius: var(--tm-radius-2xl);
  overflow: hidden;
  background:
    radial-gradient(circle at 20% 18%, rgba(198, 161, 91, 0.14), transparent 28%),
    linear-gradient(145deg, rgba(12, 12, 10, 0.9), rgba(34, 32, 27, 0.72));
}

.map-container {
  width: 100%;
  height: 100%;
}

.map-engine-chip {
  position: absolute;
  right: var(--tm-space-3);
  top: var(--tm-space-3);
  z-index: 11;
  display: inline-flex;
  align-items: center;
  gap: var(--tm-space-2);
  padding: var(--tm-space-2);
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-pill);
  background: rgba(15, 23, 42, 0.72);
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-xs);
  line-height: 1;
  box-shadow: var(--tm-shadow-card);
  backdrop-filter: var(--tm-blur-glass);
}

.map-engine-count {
  padding-right: var(--tm-space-2);
  color: var(--tm-color-text-muted);
  font-weight: 700;
}

.map-placeholder--fullscreen {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--tm-space-6);
  color: var(--tm-color-text-secondary);
  background:
    radial-gradient(circle at 50% 32%, rgba(198, 161, 91, 0.18), transparent 36%),
    rgba(7, 8, 20, 0.9);
}

.map-placeholder-card {
  display: grid;
  justify-items: center;
  gap: var(--tm-space-4);
  max-width: 420px;
  padding: var(--tm-space-8);
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-2xl);
  background: var(--tm-gradient-surface);
  text-align: center;
  box-shadow: var(--tm-shadow-card);
  backdrop-filter: var(--tm-blur-glass);
}

.map-placeholder-card--error {
  border-color: rgba(251, 113, 133, 0.36);
}

.map-placeholder-icon {
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
  border-radius: var(--tm-radius-2xl);
  background: var(--tm-color-primary-soft);
  color: var(--tm-color-cyan);
  box-shadow: var(--tm-shadow-glow);
}

.map-placeholder-card--error .map-placeholder-icon {
  background: rgba(251, 113, 133, 0.14);
  color: var(--tm-color-danger);
}

.map-placeholder-icon svg {
  width: 34px;
  height: 34px;
}

.map-placeholder-title {
  margin: 0;
  color: var(--tm-color-text-primary);
  font-size: var(--tm-font-size-xl);
  font-weight: 800;
  line-height: var(--tm-line-height-tight);
}

.map-placeholder-desc {
  margin: var(--tm-space-2) 0 0;
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-sm);
  line-height: var(--tm-line-height-normal);
}

.map-hint {
  position: absolute;
  left: var(--tm-space-3);
  right: var(--tm-space-3);
  bottom: var(--tm-space-3);
  z-index: 9;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--tm-space-2);
  max-width: 520px;
  padding: var(--tm-space-4);
  border: 1px solid rgba(251, 191, 36, 0.28);
  border-radius: var(--tm-radius-xl);
  background: rgba(15, 23, 42, 0.78);
  backdrop-filter: var(--tm-blur-glass);
  box-shadow: var(--tm-shadow-card);
  font-size: var(--tm-font-size-xs);
  line-height: var(--tm-line-height-normal);
  color: var(--tm-color-text-secondary);
  pointer-events: none;
}

.map-hint-title {
  font-weight: 800;
  color: var(--tm-color-text-primary);
}

.map-hint-sub {
  color: var(--tm-color-text-muted);
}

.day-tabs {
  position: absolute;
  top: var(--tm-space-3);
  left: var(--tm-space-3);
  display: flex;
  flex-wrap: wrap;
  gap: var(--tm-space-2);
  z-index: 10;
  max-width: calc(100% - 260px);
}

.day-tab {
  min-height: 32px;
  padding: 0 var(--tm-space-3);
  border: 1px solid var(--tm-color-border);
  border-radius: var(--tm-radius-pill);
  background: rgba(15, 23, 42, 0.68);
  backdrop-filter: var(--tm-blur-glass);
  color: var(--tm-color-text-secondary);
  font-size: var(--tm-font-size-xs);
  font-weight: 800;
  box-shadow: var(--tm-shadow-card);
  transition:
    transform var(--tm-motion-fast),
    border-color var(--tm-motion-fast),
    background var(--tm-motion-fast),
    color var(--tm-motion-fast);
}

.day-tab:hover {
  transform: translateY(-1px);
  border-color: var(--tm-color-border-strong);
  color: var(--tm-color-text-primary);
}

.day-tab.active {
  border-color: rgba(216, 192, 138, 0.42);
  background: var(--tm-gradient-brand);
  color: var(--tm-color-text-primary);
}

.day-tab:focus-visible {
  box-shadow: var(--tm-shadow-focus);
}

@media (max-width: 640px) {
  .map-engine-chip {
    left: var(--tm-space-3);
    right: auto;
    top: var(--tm-space-3);
  }

  .day-tabs {
    top: calc(var(--tm-space-3) + 44px);
    max-width: calc(100% - var(--tm-space-6));
  }

  .map-hint {
    max-width: none;
  }
}
</style>
