import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import PhaseIndicator from './PhaseIndicator.vue'
import type { PlannerPhase } from '../../types/itinerary'

const mountWith = (phase: PlannerPhase, intentLabel = '') =>
  mount(PhaseIndicator, { props: { phase, intentLabel } })

describe('PhaseIndicator', () => {
  it('is hidden when phase is idle', () => {
    const wrapper = mountWith('idle')
    expect(wrapper.find('.phase-indicator').exists()).toBe(false)
  })

  it('shows "正在生成草案" for planning phase', () => {
    const wrapper = mountWith('planning')
    expect(wrapper.text()).toContain('正在生成草案')
  })

  it('shows "正在编辑行程" for editing phase', () => {
    const wrapper = mountWith('editing')
    expect(wrapper.text()).toContain('正在编辑行程')
  })

  it('shows "需要补充信息" for clarifying phase', () => {
    const wrapper = mountWith('clarifying')
    expect(wrapper.text()).toContain('需要补充信息')
  })

  it('shows "已完成" for done phase', () => {
    const wrapper = mountWith('done')
    expect(wrapper.text()).toContain('已完成')
  })

  it('shows "请求失败" for error phase', () => {
    const wrapper = mountWith('error')
    expect(wrapper.text()).toContain('请求失败')
  })

  it('appends intentLabel in parentheses', () => {
    const wrapper = mountWith('planning', '生成行程')
    expect(wrapper.text()).toContain('（生成行程）')
  })

  it('has pulse animation on active phases', () => {
    const planning = mountWith('planning')
    expect(planning.find('.phase-indicator__pulse').exists()).toBe(true)

    const done = mountWith('done')
    expect(done.find('.phase-indicator__pulse').exists()).toBe(false)
  })

  it('applies correct CSS class for each phase', () => {
    const phases: PlannerPhase[] = ['planning', 'editing', 'clarifying', 'done', 'error']
    for (const phase of phases) {
      const wrapper = mountWith(phase)
      expect(wrapper.find(`.phase-indicator--${phase}`).exists()).toBe(true)
    }
  })
})
