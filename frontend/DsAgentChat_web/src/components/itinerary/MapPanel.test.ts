import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@amap/amap-jsapi-loader', () => ({
  default: {
    load: vi.fn().mockRejectedValue(new Error('network down')),
  },
}))

import { i18n, setAppLocale } from '../../i18n'
import MapPanel from './MapPanel.vue'

describe('MapPanel i18n', () => {
  it('retranslates an existing local map error after switching locale', async () => {
    setAppLocale('en')
    const wrapper = mount(MapPanel, {
      props: { days: [], activeDayIndex: 1 },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Map failed to load: network down')

    setAppLocale('zh-CN')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('地图加载失败: network down')
    expect(wrapper.text()).not.toContain('Map failed to load')
  })
})
