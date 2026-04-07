import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ItineraryTimeline from './ItineraryTimeline.vue'
import type { ItineraryDay } from '../../types/itinerary'

const makeDays = (overrides?: Partial<ItineraryDay>[]): ItineraryDay[] => [
  {
    day_index: 1,
    theme: '城市漫步',
    slots: [
      {
        slot: '上午',
        activity: '参观博物馆',
        place: '国家博物馆',
        cost_breakdown: { tickets: 50 },
        evidence_refs: ['ev-001'],
      },
      {
        slot: '下午',
        activity: '逛公园',
        place: '中央公园',
      },
    ],
    ...overrides?.[0],
  },
  {
    day_index: 2,
    theme: '美食之旅',
    slots: [
      {
        slot: '上午',
        activity: '早茶',
        place: '老字号茶楼',
        evidence_refs: [],
      },
    ],
    ...overrides?.[1],
  },
]

describe('ItineraryTimeline', () => {
  it('renders all days and slots', () => {
    const days = makeDays()
    const wrapper = mount(ItineraryTimeline, { props: { days } })

    expect(wrapper.findAll('.day-section')).toHaveLength(2)
    expect(wrapper.findAll('.tl-item')).toHaveLength(3)
    expect(wrapper.text()).toContain('第 1 天')
    expect(wrapper.text()).toContain('第 2 天')
    expect(wrapper.text()).toContain('参观博物馆')
    expect(wrapper.text()).toContain('城市漫步')
  })

  it('shows evidence badge only when evidence_refs is non-empty', () => {
    const days = makeDays()
    const wrapper = mount(ItineraryTimeline, { props: { days } })

    const badges = wrapper.findAll('.pc-evidence')
    expect(badges).toHaveLength(1)
    expect(badges[0].text()).toContain('已验证')
  })

  it('hides evidence badge when evidence_refs is empty or absent', () => {
    const days: ItineraryDay[] = [
      {
        day_index: 1,
        slots: [
          { slot: '上午', activity: '散步', evidence_refs: [] },
          { slot: '下午', activity: '午休' },
        ],
      },
    ]
    const wrapper = mount(ItineraryTimeline, { props: { days } })
    expect(wrapper.findAll('.pc-evidence')).toHaveLength(0)
  })

  it('applies day-changed class to matching changedDays', () => {
    const days = makeDays()
    const wrapper = mount(ItineraryTimeline, {
      props: { days, changedDays: [2] },
    })

    const sections = wrapper.findAll('.day-section')
    expect(sections[0].classes()).not.toContain('day-changed')
    expect(sections[1].classes()).toContain('day-changed')
  })

  it('does not apply day-changed when changedDays is empty', () => {
    const days = makeDays()
    const wrapper = mount(ItineraryTimeline, {
      props: { days, changedDays: [] },
    })

    const sections = wrapper.findAll('.day-section')
    sections.forEach((s) => {
      expect(s.classes()).not.toContain('day-changed')
    })
  })

  it('works without changedDays prop (undefined)', () => {
    const days = makeDays()
    const wrapper = mount(ItineraryTimeline, { props: { days } })

    const sections = wrapper.findAll('.day-section')
    sections.forEach((s) => {
      expect(s.classes()).not.toContain('day-changed')
    })
  })

  it('shows cost when cost_breakdown sums > 0', () => {
    const days = makeDays()
    const wrapper = mount(ItineraryTimeline, { props: { days } })

    const costs = wrapper.findAll('.pc-cost')
    expect(costs).toHaveLength(1)
    expect(costs[0].text()).toContain('50')
  })

  it('hides cost when no cost_breakdown', () => {
    const days: ItineraryDay[] = [
      {
        day_index: 1,
        slots: [{ slot: '上午', activity: '散步' }],
      },
    ]
    const wrapper = mount(ItineraryTimeline, { props: { days } })
    expect(wrapper.findAll('.pc-cost')).toHaveLength(0)
  })

  it('renders place and transit info', () => {
    const days: ItineraryDay[] = [
      {
        day_index: 1,
        slots: [
          {
            slot: '上午',
            activity: '游览',
            place: '故宫',
            transit: '地铁1号线',
          },
        ],
      },
    ]
    const wrapper = mount(ItineraryTimeline, { props: { days } })
    expect(wrapper.text()).toContain('故宫')
    expect(wrapper.text()).toContain('地铁1号线')
  })

  it('exposes scrollToDay method', () => {
    const days = makeDays()
    const wrapper = mount(ItineraryTimeline, { props: { days } })
    expect(typeof wrapper.vm.scrollToDay).toBe('function')
  })
})
