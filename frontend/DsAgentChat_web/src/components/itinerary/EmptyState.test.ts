import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import EmptyState from './EmptyState.vue'

describe('EmptyState', () => {
  it('renders guidance text', () => {
    const wrapper = mount(EmptyState)
    expect(wrapper.text()).toContain('你的行程将在这里呈现')
    expect(wrapper.text()).toContain('在左侧输入旅行需求')
  })

  it('renders SVG visual', () => {
    const wrapper = mount(EmptyState)
    expect(wrapper.find('svg').exists()).toBe(true)
  })
})
