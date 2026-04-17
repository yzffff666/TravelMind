<template>
  <div class="map-panel">
    <div ref="mapContainer" class="map-container" />
    <!-- 仅 SDK 未就绪时全屏遮罩；就绪后始终露出底图，避免「一片空白」的错觉 -->
    <div v-if="!mapReady" class="map-placeholder map-placeholder--fullscreen">
      <span class="map-loading-icon">🗺️</span>
      <span v-if="mapError">{{ mapError }}</span>
      <span v-else>地图加载中...</span>
    </div>
    <div
      v-else-if="slotsWithLocation.length === 0 && dayTabs.length > 0"
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

let mapInstance: any = null
let AMapLib: any = null
let markers: any[] = []
let polyline: any = null
let infoWindow: any = null
let _mapLoading = false  // 防止并发 initMap

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

const slotsWithLocation = computed((): { slot: ItinerarySlot; idx: number; loc: Location }[] => {
  if (!activeDay.value) return []
  return activeDay.value.slots
    .filter((s) => s.location != null)
    .map((s, i) => ({ slot: s, idx: i, loc: s.location as Location }))
})

async function initMap() {
  if (_mapLoading || mapInstance) return  // 防并发
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

    await nextTick()
    renderMarkers()
  } catch (e: any) {
    mapError.value = `地图加载失败: ${e.message || e}`
  } finally {
    _mapLoading = false
  }
}

function clearMap() {
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

function renderMarkers() {
  if (!mapInstance || !AMapLib) return
  clearMap()

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

function highlightSlot(slotIdx: number) {
  if (!infoWindow || !mapInstance) return
  const item = slotsWithLocation.value.find(s => s.idx === slotIdx)
  if (!item) return
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
}

watch(() => props.activeDayIndex, () => {
  renderMarkers()
})

watch(() => props.activeSlotIndex, (val) => {
  if (val != null) highlightSlot(val)
})

// 监听天数变化和每天 slots 坐标变化（用 length + 首个坐标做浅比较，避免 deep watch 遍历整棵树）
watch(
  () => props.days.map(d => `${d.day_index}:${d.slots.filter(s => s.location).length}`).join(','),
  () => { renderMarkers() }
)

onMounted(() => {
  initMap()
})

onBeforeUnmount(() => {
  clearMap()
  mapInstance?.destroy()
  mapInstance = null
  AMapLib = null
  infoWindow = null
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
