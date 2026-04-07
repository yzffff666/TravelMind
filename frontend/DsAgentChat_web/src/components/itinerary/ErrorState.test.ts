import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ErrorState from './ErrorState.vue'

describe('ErrorState', () => {
  it('displays error text', () => {
    const wrapper = mount(ErrorState, {
      props: { errorText: '网络超时，请稍后重试' },
    })
    expect(wrapper.text()).toContain('网络超时，请稍后重试')
  })

  it('displays default text when errorText is empty', () => {
    const wrapper = mount(ErrorState, { props: { errorText: '' } })
    expect(wrapper.text()).toContain('请检查网络连接')
  })

  it('emits retry when retry button clicked', async () => {
    const wrapper = mount(ErrorState, { props: { errorText: '失败' } })
    await wrapper.find('.btn-retry').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('emits reset when reset button clicked', async () => {
    const wrapper = mount(ErrorState, { props: { errorText: '失败' } })
    await wrapper.find('.btn-reset').trigger('click')
    expect(wrapper.emitted('reset')).toHaveLength(1)
  })

  it('shows both retry and reset buttons', () => {
    const wrapper = mount(ErrorState, { props: { errorText: '失败' } })
    expect(wrapper.find('.btn-retry').exists()).toBe(true)
    expect(wrapper.find('.btn-reset').exists()).toBe(true)
  })
})
