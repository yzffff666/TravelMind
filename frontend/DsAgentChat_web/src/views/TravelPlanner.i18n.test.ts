import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import { createTestI18n } from '../test/i18n'
import TravelPlanner from './TravelPlanner.vue'

async function mountPlanner(locale: 'en' | 'zh-CN') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: TravelPlanner }],
  })
  await router.push('/')
  await router.isReady()

  return mount(TravelPlanner, {
    global: {
      plugins: [createTestI18n(locale), router],
      stubs: { MapPanel: true },
    },
  })
}

describe('TravelPlanner i18n', () => {
  it('is English-first and exposes a locale switch', async () => {
    const wrapper = await mountPlanner('en')

    expect(wrapper.text()).toContain('Turn your next journey into a plan')
    expect(wrapper.text()).toContain('Ready to plan')
    expect(wrapper.find('[data-locale="zh-CN"]').exists()).toBe(true)
  })

  it('renders Chinese workspace copy for Chinese locale', async () => {
    const wrapper = await mountPlanner('zh-CN')

    expect(wrapper.text()).toContain('把下一段旅程')
    expect(wrapper.text()).toContain('准备规划')
  })
})
