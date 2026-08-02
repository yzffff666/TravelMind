import { createI18n } from 'vue-i18n'

import en from './messages/en'
import zhCN from './messages/zh-CN'

export type AppLocale = 'en' | 'zh-CN'

export const LOCALE_STORAGE_KEY = 'travelmind.ui_locale'

const DEFAULT_LOCALE: AppLocale = 'en'

function isAppLocale(value: string | null): value is AppLocale {
  return value === 'en' || value === 'zh-CN'
}

export function resolveInitialLocale(storage?: Pick<Storage, 'getItem'>): AppLocale {
  const localeStorage = storage ?? (
    typeof window === 'undefined' ? undefined : window.localStorage
  )

  if (!localeStorage) return DEFAULT_LOCALE

  try {
    const storedLocale = localeStorage.getItem(LOCALE_STORAGE_KEY)
    return isAppLocale(storedLocale) ? storedLocale : DEFAULT_LOCALE
  } catch {
    return DEFAULT_LOCALE
  }
}

const initialLocale = resolveInitialLocale()

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale: DEFAULT_LOCALE,
  messages: {
    en,
    'zh-CN': zhCN,
  },
  numberFormats: {
    en: {
      integer: { maximumFractionDigits: 0 },
    },
    'zh-CN': {
      integer: { maximumFractionDigits: 0 },
    },
  },
})

function syncDocumentLocale(locale: AppLocale) {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = locale
  }
}

export function setAppLocale(locale: AppLocale) {
  i18n.global.locale.value = locale

  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
    } catch {
      // Locale still updates when storage is unavailable (for example private mode).
    }
  }

  syncDocumentLocale(locale)
}

syncDocumentLocale(initialLocale)
