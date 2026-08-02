import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import PhaseIndicator from './PhaseIndicator.vue'
import type { PlannerPhase } from '../../types/itinerary'
import { createTestI18n } from '../../test/i18n'

const mountWith = (phase: PlannerPhase, intentLabel = '', intent = '') =>
  mount(PhaseIndicator, {
    props: { phase, intentLabel, intent } as any,
    global: { plugins: [createTestI18n('en')] },
  })

describe('PhaseIndicator', () => {
  it('is hidden when phase is idle', () => {
    const wrapper = mountWith('idle')
    expect(wrapper.find('.phase-indicator').exists()).toBe(false)
  })

  it('shows an English planning state', () => {
    const wrapper = mountWith('planning')
    expect(wrapper.text()).toContain('Building draft')
  })

  it('shows "正在编辑行程" for editing phase', () => {
    const wrapper = mountWith('editing')
    expect(wrapper.text()).toContain('Editing itinerary')
  })

  it('shows "需要补充信息" for clarifying phase', () => {
    const wrapper = mountWith('clarifying')
    expect(wrapper.text()).toContain('More information needed')
  })

  it('shows "已完成" for done phase', () => {
    const wrapper = mountWith('done')
    expect(wrapper.text()).toContain('Completed')
  })

  it('uses QA-specific done description', () => {
    const wrapper = mountWith('done', 'Itinerary Q&A', 'qa')
    expect(wrapper.text()).toContain('Your question was answered without changing the itinerary.')
  })

  it('shows "请求失败" for error phase', () => {
    const wrapper = mountWith('error')
    expect(wrapper.text()).toContain('Request failed')
  })

  it('appends intentLabel in parentheses', () => {
    const wrapper = mountWith('planning', 'Create itinerary')
    expect(wrapper.text()).toContain('(Create itinerary)')
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
