import { beforeEach, describe, expect, it } from 'vitest'

import {
  LOCALE_STORAGE_KEY,
  i18n,
  resolveInitialLocale,
  setAppLocale,
} from './index'

describe('frontend locale policy', () => {
  beforeEach(() => {
    localStorage.clear()
    setAppLocale('en')
  })

  it('defaults unsupported or missing locale values to English', () => {
    expect(resolveInitialLocale(localStorage)).toBe('en')

    localStorage.setItem(LOCALE_STORAGE_KEY, 'fr')
    expect(resolveInitialLocale(localStorage)).toBe('en')
  })

  it('restores a supported Chinese locale', () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, 'zh-CN')
    expect(resolveInitialLocale(localStorage)).toBe('zh-CN')
  })

  it('persists locale changes and updates document language', () => {
    setAppLocale('zh-CN')

    expect(i18n.global.locale.value).toBe('zh-CN')
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
  })
})
