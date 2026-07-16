import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DiffCard from './DiffCard.vue'
import type { EditDiffData } from '../../types/itinerary'

const makeDiff = (overrides?: Partial<EditDiffData>): EditDiffData => ({
  summary: {
    changed_days: [1, 3],
    diff_items: [
      '第1天上午：「参观博物馆」→「逛书店」',
      '第3天下午：已删除「登山」',
    ],
  },
  explanation: '已修改第1天、第3天',
  ...overrides,
})

describe('DiffCard', () => {
  it('renders diff header', () => {
    const wrapper = mount(DiffCard, { props: { diff: makeDiff() } })
    expect(wrapper.find('.diff-title').text()).toBe('行程已修改')
  })

  it('renders all diff_items', () => {
    const diff = makeDiff()
    const wrapper = mount(DiffCard, { props: { diff } })

    const items = wrapper.findAll('.diff-item')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain('参观博物馆')
    expect(items[1].text()).toContain('已删除')
  })

  it('renders changed_days tags', () => {
    const diff = makeDiff()
    const wrapper = mount(DiffCard, { props: { diff } })

    const tags = wrapper.findAll('.diff-day-tag')
    expect(tags).toHaveLength(2)
    expect(tags[0].text()).toBe('第 1 天')
    expect(tags[1].text()).toBe('第 3 天')
  })

  it('renders explanation', () => {
    const diff = makeDiff()
    const wrapper = mount(DiffCard, { props: { diff } })
    expect(wrapper.find('.diff-explanation').text()).toBe('已修改第1天、第3天')
  })

  it('hides diff_items list when empty', () => {
    const diff = makeDiff({
      summary: { changed_days: [1], diff_items: [] },
    })
    const wrapper = mount(DiffCard, { props: { diff } })
    expect(wrapper.findAll('.diff-item')).toHaveLength(0)
  })

  it('hides changed_days section when empty', () => {
    const diff = makeDiff({
      summary: { changed_days: [], diff_items: ['something'] },
    })
    const wrapper = mount(DiffCard, { props: { diff } })
    expect(wrapper.findAll('.diff-day-tag')).toHaveLength(0)
  })

  it('hides explanation when empty', () => {
    const diff = makeDiff({ explanation: '' })
    const wrapper = mount(DiffCard, { props: { diff } })
    expect(wrapper.find('.diff-explanation').exists()).toBe(false)
  })

  it('hides explanation when it repeats a diff item', () => {
    const diff = makeDiff({
      summary: {
        changed_days: [2],
        diff_items: ['第2天按「室内」重新规划（原安排：豫园、田子坊）'],
      },
      explanation: '已修改 第2天。第2天按「室内」重新规划（原安排：豫园、田子坊）。',
    })
    const wrapper = mount(DiffCard, { props: { diff } })
    expect(wrapper.find('.diff-explanation').exists()).toBe(false)
  })
})
