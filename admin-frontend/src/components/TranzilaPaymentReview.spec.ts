import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'
import TranzilaPaymentReview from './TranzilaPaymentReview.vue'

enableAutoUnmount(afterEach)
vi.mock('@/services/api', () => ({ apiFetch: vi.fn(), formatApiError: (e: Error) => e.message }))
const props = { checkoutId: 'order-1', status: 'paid', transactionIndex: '123', canManage: true, refunds: [] }
beforeEach(() => { vi.mocked(apiFetch).mockReset(); useI18n().locale.value = 'en' })

describe('TranzilaPaymentReview', () => {
  it('requires finance permission for actions but keeps refund history visible', () => {
    const wrapper = mount(TranzilaPaymentReview, { props: { ...props, canManage: false,
      refunds: [{ id: 1, amount: '2.00', provider_reference: 'REF-1', actor: 'operator', created_at: '2026-09-12T12:00:00Z', adjusted_at: null, adjustment_reference: '', adjusted_by: null }] } })
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).toContain('Wallet/membership adjustment pending')
    expect(wrapper.text()).toContain('REF-1')
  })
  it('reconciles the selected transaction and refreshes its parent only on success', async () => {
    const wrapper = mount(TranzilaPaymentReview, { props })
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error('Unavailable'))
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.emitted('changed')).toBeUndefined()
    expect(wrapper.get('[role=alert]').text()).toContain('Unavailable')
    vi.mocked(apiFetch).mockResolvedValueOnce({ status: 'paid' })
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(apiFetch).toHaveBeenLastCalledWith('/api/admin/checkouts/order-1/reconcile', { method: 'POST', body: '{"transaction_index":123}' })
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })
  it('retains the refund retry key after uncertain failure and requires external confirmation', async () => {
    const wrapper = mount(TranzilaPaymentReview, { props })
    const form = wrapper.get('details form')
    expect(form.get('button').attributes('disabled')).toBeDefined()
    await form.get('input[type=number]').setValue('2.00')
    await form.get('input[maxlength]').setValue('REF-123')
    await form.get('input[type=checkbox]').setValue(true)
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error('Timeout')).mockResolvedValueOnce({ id: 1 })
    await form.trigger('submit'); await flushPromises()
    await form.trigger('submit'); await flushPromises()
    const [first, second] = vi.mocked(apiFetch).mock.calls
    expect(first?.[1]?.body).toBe(second?.[1]?.body)
    expect(JSON.parse(String(first?.[1]?.body))).toMatchObject({ provider_reference: 'REF-123', confirmed_in_provider: true })
    expect(wrapper.text()).toContain('does not send a refund')
  })
})
