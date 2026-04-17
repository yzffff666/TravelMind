<template>
  <div class="map-panel">
    <div ref="mapContainer" class="map-container" />
    <div v-if="!mapReady" class="map-placeholder map-placeholder--fullscreen">
      <span class="map-loading-icon">🗺️</span>
      <span v-if="mapError">{{ mapError }}</span>
      <span v-else>地图加载中...</span>
    </div>
    <div v-if="mapReady" class="map-engine-chip">
      {{ mapEngine === 'leaflet' ? 'Overseas: OpenStreetMap' : 'China: Gaode Map' }}
    </div>
    <div
      v-if="mapReady && slotsWithLocation.length === 0 && dayTabs.length > 0"
      class="map-hint"
    >
      <span class="map-hint-title">本日暂无坐标点</span>
      <span class="map-hint-sub">可切换其他 Day；生成完成后会显示标记与路线</span>
      <span class="map-hint-key">若底图只有网格、无道路，多为 Key 未开通「Web端(JS API)」，与后端 Web 服务 Key 需分开配置</span>
    </div>
    <div v-if="mapReady && dayTabs.length > 0" class="day-tabs">
      <button
        v-for="tab in dayTabs"
        :key="tab.index"
        :class="['day-tab', { active: tab.index === activeDayIndex }]"
        @click="$emit('selectDay', tab.index)"
      >
        Day {{ tab.index }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, computed, nextTick } from 'vue'
import type { ItineraryDay, ItinerarySlot, Location } from '@/types/itinerary'
import AMapLoader from '@amap/amap-jsapi-loader'

const props = defineProps<{
  days: ItineraryDay[]
  activeDayIndex: number
  activeSlotIndex?: number
}>()

const emit = defineEmits<{
  selectDay: [dayIndex: number]
  selectSlot: [dayIndex: number, slotIndex: number]
}>()

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
  '上午': '#3B82F6',
  '下午': '#F59E0B',
  '晚上': '#8B5CF6',
}
const DEFAULT_COLOR = '#10B981'

const dayTabs = computed(() =>
  props.days.map(d => ({ index: d.day_index, theme: d.theme }))
)

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
    mapError.value = '请配置 VITE_AMAP_KEY（高德地图 Web API Key）'
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
    mapError.value = `地图加载失败: ${e.message || e}`
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
    renderLeafletMarkers()
  } catch (e: any) {
    mapError.value = `海外地图加载失败: ${e.message || e}`
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
    mapError.value = `地图刷新失败: ${e?.message || e}`
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
      strokeColor: '#6366F1',
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
      color: '#6366F1',
      weight: 3,
      opacity: 0.7,
      dashArray: '8, 6',
      lineJoin: 'round',
    }).addTo(mapInstance)
  }

  const bounds = leafletLib.latLngBounds(latLngs)
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
  border-radius: 12px;
  overflow: hidden;
  background: #f0f2f5;
}

.map-container {
  width: 100%;
  height: 100%;
}

.map-engine-chip {
  position: absolute;
  right: 12px;
  top: 12px;
  z-index: 11;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 11px;
  line-height: 1;
}

.map-placeholder--fullscreen {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #999;
  font-size: 14px;
  background: rgba(240, 242, 245, 0.92);
}

.map-hint {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 12px;
  z-index: 9;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(6px);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  font-size: 12px;
  line-height: 1.45;
  color: #555;
  pointer-events: none;
}

.map-hint-title {
  font-weight: 600;
  color: #333;
}

.map-hint-sub {
  color: #666;
}

.map-hint-key {
  margin-top: 2px;
  font-size: 11px;
  color: #888;
}

.map-loading-icon {
  font-size: 36px;
}

.day-tabs {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  gap: 4px;
  z-index: 10;
}

.day-tab {
  padding: 4px 12px;
  border: none;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(4px);
  font-size: 12px;
  font-weight: 600;
  color: #666;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
  transition: all 0.2s ease;
}

.day-tab:hover {
  background: #fff;
  color: #333;
}

.day-tab.active {
  background: #6366f1;
  color: #fff;
}
</style>
