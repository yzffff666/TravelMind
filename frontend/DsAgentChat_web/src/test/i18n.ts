import { createI18n } from 'vue-i18n'

import en from '../i18n/messages/en'
import zhCN from '../i18n/messages/zh-CN'
import type { AppLocale } from '../i18n'

export function createTestI18n(locale: AppLocale = 'en') {
  return createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en',
    messages: { en, 'zh-CN': zhCN },
    numberFormats: {
      en: { integer: { maximumFractionDigits: 0 } },
      'zh-CN': { integer: { maximumFractionDigits: 0 } },
    },
  })
}
