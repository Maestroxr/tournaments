import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'
import TranzilaReadiness from './TranzilaReadiness.vue'

vi.mock('@/services/api', () => ({
  apiFetch: vi.fn(),
  formatApiError: (error: unknown) => error instanceof Error ? error.message : 'Request failed',
}))
const response = (ready = false) => ({
  ready, enabled: ready, environment: 'test',
  checks: ['enabled', 'terminal', 'api_key', 'api_secret', 'return_url', 'notify_url'].map(key => ({ key, configured: ready })),
  automatic_fulfillment: false, recurring_enabled: false,
})
const render = () => mount(TranzilaReadiness, { global: { stubs: {
  Button: { props: ['label', 'disabled'], template: '<button :disabled="disabled">{{ label }}</button>' },
} } })

describe('TranzilaReadiness', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
    useI18n().locale.value = 'he'
  })

  it('shows missing settings while disabled and never displays credential values', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...response(), api_secret: 'private-secret' })
    const wrapper = render()
    await flushPromises()
    expect(apiFetch).toHaveBeenCalledWith('/api/admin/tranzila-readiness')
    expect(wrapper.text()).toContain('החיבור כבוי')
    expect(wrapper.findAll('dd').every(item => item.text() === 'חסר')).toBe(true)
    expect(wrapper.text()).toContain('סוד API')
    expect(wrapper.text()).not.toContain('private-secret')
    expect(wrapper.findAll('input')).toHaveLength(0)
  })

  it('refreshes into terminal testing readiness without claiming production readiness', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(response()).mockResolvedValueOnce(response(true))
    const wrapper = render()
    await flushPromises()
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('מוכן לבדיקת מסוף')
    expect(wrapper.text()).toContain('לפני הפעלה בייצור')
    expect(wrapper.text()).toContain('זיכוי קויינס והפעלת מנוי אוטומטיים ממתינים')
    expect(wrapper.text()).toContain('ללא חידוש אוטומטי')
    expect(wrapper.findAll('dd').every(item => item.text() === 'מוגדר')).toBe(true)
    expect(apiFetch).toHaveBeenCalledTimes(2)
  })

  it('clears stale readiness on refresh failure and allows retry in English', async () => {
    useI18n().locale.value = 'en'
    vi.mocked(apiFetch).mockResolvedValueOnce(response(true)).mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValueOnce(response())
    const wrapper = render()
    await flushPromises()
    expect(wrapper.text()).toContain('Ready for terminal testing')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('Unavailable')
    expect(wrapper.text()).not.toContain('Ready for terminal testing')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Connection disabled')
  })

  it('labels report mapping and hides completion notes for validated capabilities', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...response(true),
      checks: [{ key: 'report_mapping', configured: true }],
      automatic_fulfillment: true, recurring_enabled: true,
    })
    const wrapper = render()
    await flushPromises()
    expect(wrapper.text()).toContain('אישור מיפוי שדות דוח העסקאות')
    expect(wrapper.text()).not.toContain('אוטומטיים ממתינים')
    expect(wrapper.text()).not.toContain('חיובים חוזרים ממתינים')
  })
})
