import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { LOCALE_STORAGE_KEY, i18n, setAppLocale } from '../../i18n'
import LocaleSwitch from './LocaleSwitch.vue'

describe('LocaleSwitch', () => {
  beforeEach(() => {
    localStorage.clear()
    setAppLocale('en')
  })

  it('renders an accessible English-first segmented control', () => {
    const wrapper = mount(LocaleSwitch, { global: { plugins: [i18n] } })

    expect(wrapper.get('[role="group"]').attributes('aria-label')).toBe('Interface language')
    expect(wrapper.get('[data-locale="en"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-locale="zh-CN"]').attributes('aria-pressed')).toBe('false')
  })

  it('switches to Chinese and persists the preference', async () => {
    const wrapper = mount(LocaleSwitch, { global: { plugins: [i18n] } })

    await wrapper.get('[data-locale="zh-CN"]').trigger('click')

    expect(i18n.global.locale.value).toBe('zh-CN')
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN')
    expect(wrapper.get('[role="group"]').attributes('aria-label')).toBe('界面语言')
  })
})
