import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import EmptyState from './EmptyState.vue'
import { createTestI18n } from '../../test/i18n'

const mountEmpty = (locale: 'en' | 'zh-CN' = 'en') => mount(EmptyState, {
  global: { plugins: [createTestI18n(locale)] },
})

describe('EmptyState', () => {
  it('renders guidance text', () => {
    const wrapper = mountEmpty()
    expect(wrapper.text()).toContain('Your itinerary will appear here')
    expect(wrapper.text()).toContain('popular destinations')
  })

  it('renders SVG visual', () => {
    const wrapper = mountEmpty()
    expect(wrapper.find('svg').exists()).toBe(true)
  })

  it('renders suggestion cards', () => {
    const wrapper = mountEmpty()
    const cards = wrapper.findAll('.sg-card')
    expect(cards.length).toBeGreaterThanOrEqual(4)
    expect(wrapper.text()).toContain('Tokyo')
  })

  it('emits suggest when card clicked', async () => {
    const wrapper = mountEmpty()
    await wrapper.find('.sg-card').trigger('click')
    expect(wrapper.emitted('suggest')).toBeTruthy()
    expect(wrapper.emitted('suggest')![0][0]).toContain('Tokyo')
  })
})
