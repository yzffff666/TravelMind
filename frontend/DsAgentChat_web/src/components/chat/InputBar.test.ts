import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { createTestI18n } from '../../test/i18n'
import InputBar from './InputBar.vue'

describe('InputBar i18n', () => {
  it('uses English interface copy by default', () => {
    const wrapper = mount(InputBar, {
      props: { isStreaming: false, canReset: true },
      global: { plugins: [createTestI18n('en')] },
    })

    expect(wrapper.get('textarea').attributes('placeholder')).toContain('destination')
    expect(wrapper.get('.btn-reset').text()).toBe('Reset')
  })

  it('renders Chinese controls in Chinese locale', () => {
    const wrapper = mount(InputBar, {
      props: { isStreaming: false, canReset: true },
      global: { plugins: [createTestI18n('zh-CN')] },
    })

    expect(wrapper.get('textarea').attributes('placeholder')).toContain('目的地')
    expect(wrapper.get('.btn-reset').text()).toBe('重置')
  })
})
