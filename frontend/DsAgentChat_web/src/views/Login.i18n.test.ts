import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import { i18n, setAppLocale } from '../i18n'
import Login from './Login.vue'

async function mountLogin(locale: 'en' | 'zh-CN', path = '/login') {
  setAppLocale(locale)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', component: Login },
      { path: '/register', component: Login },
      { path: '/', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()

  return mount(Login, {
    global: {
      plugins: [createPinia(), i18n, router],
      stubs: { MessageBox: true },
    },
  })
}

describe('Login i18n', () => {
  it('renders an English-first sign-in screen with a locale switch', async () => {
    const wrapper = await mountLogin('en')

    expect(wrapper.text()).toContain('Welcome back')
    expect(wrapper.text()).toContain('Continue planning your next journey')
    expect(wrapper.text()).toContain('Sign in')
    expect(wrapper.find('[data-locale="zh-CN"]').exists()).toBe(true)
  })

  it('renders the Chinese register route', async () => {
    const wrapper = await mountLogin('zh-CN', '/register')

    expect(wrapper.text()).toContain('创建 TravelMind 账号')
    expect(wrapper.text()).toContain('用户名')
    expect(wrapper.text()).toContain('注册')
  })

  it('retranslates an existing validation error when the locale changes', async () => {
    const wrapper = await mountLogin('en')

    await wrapper.get('input[type="email"]').setValue('not-an-email')
    expect(wrapper.text()).toContain('Enter a valid email address')

    await wrapper.get('[data-locale="zh-CN"]').trigger('click')
    expect(wrapper.text()).toContain('请输入有效的邮箱地址')
    expect(wrapper.text()).not.toContain('Enter a valid email address')
  })
})
