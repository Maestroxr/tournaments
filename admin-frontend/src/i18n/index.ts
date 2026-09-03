import { computed, ref, watchEffect } from 'vue'
import { messages, type Locale } from './messages'

const STORAGE_KEY = 'backgammon-admin-locale'
const locales = Object.keys(messages) as Locale[]

const initialLocale = (): Locale => {
  if (typeof localStorage !== 'undefined') {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && locales.includes(saved as Locale)) return saved as Locale
  }
  return typeof navigator !== 'undefined' && navigator.language.startsWith('he') ? 'he' : 'en'
}

const locale = ref<Locale>(initialLocale())
const direction = computed(() => (locale.value === 'he' ? 'rtl' : 'ltr'))

watchEffect(() => {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = locale.value
    document.documentElement.dir = direction.value
  }
  if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, locale.value)
})

function lookup(key: string): string | undefined {
  return key.split('.').reduce<unknown>((value, part) => {
    if (value && typeof value === 'object' && part in value) return (value as Record<string, unknown>)[part]
    return undefined
  }, messages[locale.value]) as string | undefined
}

export function t(key: string, params: Record<string, string | number> = {}) {
  const template = lookup(key) ?? key
  return Object.entries(params).reduce((text, [name, value]) => text.split(`{${name}}`).join(String(value)), template)
}

export function toggleLocale() {
  locale.value = locale.value === 'he' ? 'en' : 'he'
}

export function useI18n() {
  return { locale, direction, locales, t, toggleLocale }
}
