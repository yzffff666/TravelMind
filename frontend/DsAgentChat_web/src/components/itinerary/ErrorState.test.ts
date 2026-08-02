import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ErrorState from './ErrorState.vue'
import { createTestI18n } from '../../test/i18n'

const mountError = (errorText: string, locale: 'en' | 'zh-CN' = 'en') => mount(ErrorState, {
  props: { errorText },
  global: { plugins: [createTestI18n(locale)] },
})

describe('ErrorState', () => {
  it('displays error text', () => {
    const wrapper = mountError('Network timed out')
    expect(wrapper.text()).toContain('Network timed out')
  })

  it('displays default text when errorText is empty', () => {
    const wrapper = mountError('')
    expect(wrapper.text()).toContain('Check your connection')
  })

  it('emits retry when retry button clicked', async () => {
    const wrapper = mountError('Failed')
    await wrapper.find('.btn-retry').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('emits reset when reset button clicked', async () => {
    const wrapper = mountError('Failed')
    await wrapper.find('.btn-reset').trigger('click')
    expect(wrapper.emitted('reset')).toHaveLength(1)
  })

  it('shows both retry and reset buttons', () => {
    const wrapper = mountError('Failed')
    expect(wrapper.find('.btn-retry').exists()).toBe(true)
    expect(wrapper.find('.btn-reset').exists()).toBe(true)
  })
})
