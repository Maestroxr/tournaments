import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'
import TranzilaOperations from './TranzilaOperations.vue'

enableAutoUnmount(afterEach)
vi.mock('@/services/api', () => ({ apiFetch: vi.fn(), formatApiError: (e: Error) => e.message }))
const state = { can_manage: true, runs: [], issue_count: 0, issues: [] }
beforeEach(() => { vi.mocked(apiFetch).mockReset(); useI18n().locale.value = 'en' })
it('makes a deliberate report check and reports failure without a stale success', async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(state)
  const wrapper = mount(TranzilaOperations); await flushPromises()
  expect(apiFetch).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('No check recorded yet')
  vi.mocked(apiFetch).mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValueOnce({ ...state,
    runs: [{ id: 1, kind: 'health', status: 'failed', started_at: '2026-09-12T12:00:00Z', finished_at: null }] })
  await wrapper.findAll('button')[1]!.trigger('click'); await flushPromises()
  expect(apiFetch).toHaveBeenCalledWith('/api/admin/tranzila-health', { method: 'POST' })
  expect(wrapper.text()).toContain('Failed')
  expect(wrapper.get('[role=alert]').text()).toContain('Unavailable')
})
it('shows an unresolved issue to viewers without management actions', async () => {
  vi.mocked(apiFetch).mockResolvedValue({ ...state, can_manage: false, issue_count: 1,
    issues: [{ id: 1, transaction_index: '42', code: 'unmatched_transaction', checkout_id: null }] })
  const wrapper = mount(TranzilaOperations); await flushPromises()
  expect(wrapper.text()).toContain('Transaction without matching order')
  expect(wrapper.find('form').exists()).toBe(false)
  expect(wrapper.findAll('button')).toHaveLength(1)
})
