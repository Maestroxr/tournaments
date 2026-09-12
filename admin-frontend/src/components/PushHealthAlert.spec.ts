import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'
import PushHealthAlert from './PushHealthAlert.vue'

enableAutoUnmount(afterEach)
vi.mock('@/services/api', () => ({ apiFetch: vi.fn() }))
beforeEach(() => {
  vi.mocked(apiFetch).mockReset()
  useI18n().locale.value = 'he'
})
afterEach(() => vi.useRealTimers())

it('shows server problems in Hebrew and hides them after recovery', async () => {
  vi.mocked(apiFetch).mockResolvedValue({ issues: [
    { code: 'configuration_missing', fields: ['WEB_PUSH_PRIVATE_KEY'] },
    { code: 'failed', count: 3 },
  ] })
  const wrapper = mount(PushHealthAlert)
  await flushPromises()
  expect(wrapper.get('[role=alert]').text()).toContain('חסרות הגדרות')
  expect(wrapper.text()).toContain('WEB_PUSH_PRIVATE_KEY')
  expect(wrapper.text()).toContain('3')
  vi.mocked(apiFetch).mockResolvedValue({ issues: [] })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role=alert]').exists()).toBe(false)
})

it('reports unavailable monitoring and allows retry in English', async () => {
  useI18n().locale.value = 'en'
  vi.mocked(apiFetch).mockRejectedValue(new Error('Server error'))
  const wrapper = mount(PushHealthAlert)
  await flushPromises()
  expect(wrapper.text()).toContain('status could not be checked')
  vi.mocked(apiFetch).mockResolvedValue({ issues: [{ code: 'worker_stopped' }] })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('worker is not reporting activity')
  expect(wrapper.text()).not.toContain('status could not be checked')
})

it('polls for new problems and stops polling when unmounted', async () => {
  vi.useFakeTimers()
  vi.mocked(apiFetch).mockResolvedValue({ issues: [] })
  const wrapper = mount(PushHealthAlert)
  await flushPromises()
  expect(wrapper.find('[role=alert]').exists()).toBe(false)
  vi.mocked(apiFetch).mockResolvedValue({ issues: [{ code: 'delayed', count: 2 }] })
  await vi.advanceTimersByTimeAsync(30000)
  expect(wrapper.text()).toContain('יותר משתי דקות')
  wrapper.unmount()
  const calls = vi.mocked(apiFetch).mock.calls.length
  await vi.advanceTimersByTimeAsync(30000)
  expect(apiFetch).toHaveBeenCalledTimes(calls)
})
