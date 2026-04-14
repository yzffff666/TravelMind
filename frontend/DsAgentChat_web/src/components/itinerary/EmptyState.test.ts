import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import EmptyState from './EmptyState.vue'

describe('EmptyState', () => {
  it('renders guidance text', () => {
    const wrapper = mount(EmptyState)
    expect(wrapper.text()).toContain('你的行程将在这里呈现')
    expect(wrapper.text()).toContain('热门目的地')
  })

  it('renders SVG visual', () => {
    const wrapper = mount(EmptyState)
    expect(wrapper.find('svg').exists()).toBe(true)
  })

  it('renders suggestion cards', () => {
    const wrapper = mount(EmptyState)
    const cards = wrapper.findAll('.sg-card')
    expect(cards.length).toBeGreaterThanOrEqual(4)
    expect(wrapper.text()).toContain('东京')
  })

  it('emits suggest when card clicked', async () => {
    const wrapper = mount(EmptyState)
    await wrapper.find('.sg-card').trigger('click')
    expect(wrapper.emitted('suggest')).toBeTruthy()
    expect(wrapper.emitted('suggest')![0][0]).toContain('东京')
  })
})
