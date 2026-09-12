import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PrimeVue from 'primevue/config'
import AutoComplete from 'primevue/autocomplete'
import PaymentsView from './PaymentsView.vue'
import { useI18n } from '@/i18n'

const api = vi.hoisted(() => vi.fn())
enableAutoUnmount(afterEach)
afterEach(() => vi.useRealTimers())
vi.mock('@/services/api', () => ({ apiFetch: api, formatApiError: (e: unknown) => String(e) }))
const result = {
  count: 1, legacy_count: 0, legacy_payments: [], totals: [],
  items: [{ id: 'request-1', username: 'dana', actor: 'admin', product: 'coins', tier: '',
    amount: '10.00', currency: 'ILS', coin_quantity: 500, status: 'draft', environment: 'sandbox',
    provider_reference: null, created_at: '2026-09-11T10:00:00Z',
    events: [{ kind: 'draft_created', actor: 'admin', created_at: '2026-09-11T10:00:00Z' }] }],
}
const catalog = { items: [
  { id: 1, name: '500 coins', kind: 'coins', tier: '', price: '10.00', currency: 'ILS', coin_quantity: 500, period_months: 0, active: true },
  { id: 2, name: 'Gold quarterly', kind: 'subscription', tier: 'GOLD', price: '30.00', currency: 'USD', coin_quantity: 0, period_months: 3, active: true },
  { id: 3, name: 'Inactive package', kind: 'coins', price: '5.00', active: false },
  { id: 4, name: 'Free tier', kind: 'subscription', price: '0.00', active: true },
] }
function render() { return mount(PaymentsView, { global: { plugins: [PrimeVue], stubs: { TranzilaReadiness: true, TranzilaCheckoutAction: true, RouterLink: { template: '<a><slot /></a>' } } } }) }
describe('PaymentsView', () => {
  beforeEach(() => {
    api.mockReset()
    api.mockImplementation((url: string) => Promise.resolve(url === '/api/admin/store-catalog' ? catalog : result))
    useI18n().locale.value = 'en'
  })
  it('shows separate money, coins, author and audit history without a charge action', async () => {
    const wrapper = render(); await flushPromises()
    expect(wrapper.text()).toContain('awaiting connection')
    expect(wrapper.text()).toContain('dana')
    expect(wrapper.text()).toContain('500')
    expect(wrapper.text()).toContain('Draft created')
    expect(wrapper.text()).toContain('admin')
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    expect(api).toHaveBeenCalledTimes(2)
  })
  it('applies search and status filters to the backend', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.find('input[type="search"]').setValue('dana')
    const form = wrapper.findAll('form')[1]!
    await form.findAll('select')[1]!.setValue('failed')
    await form.trigger('submit'); await flushPromises()
    expect(api).toHaveBeenLastCalledWith('/api/admin/checkouts?q=dana&status=failed&product=&offset=0')
  })
  it('renders Hebrew labels and recoverable load errors', async () => {
    useI18n().locale.value = 'he'; api.mockRejectedValue(new Error('Offline'))
    const wrapper = render(); await flushPromises()
    expect(wrapper.text()).toContain('תשלומים ורכישות')
    expect(wrapper.find('[role="alert"]').text()).toContain('Offline')
  })
  it('uses catalog pricing and sends only the selected product and user to create a request', async () => {
    const wrapper = render(); await flushPromises()
    const form = wrapper.findAll('form')[0]!
    expect(form.text()).not.toContain('Inactive package')
    expect(form.text()).not.toContain('Free tier')
    expect(form.find('input[type="number"]').exists()).toBe(false)
    await form.find('select').setValue('1')
    wrapper.findComponent(AutoComplete).vm.$emit('update:modelValue', { id: 8, username: 'dana' })
    await flushPromises()
    expect(form.findAll('output').map(item => item.text())).toEqual([expect.stringContaining('10.00'), 'ILS', '500'])
    await form.trigger('submit'); await flushPromises()
    const post = api.mock.calls.find(call => call[1]?.method === 'POST')!
    expect(post[0]).toBe('/api/admin/checkouts')
    expect(JSON.parse(post[1].body)).toEqual({ user_id: 8, catalog_product_id: 1, idempotency_key: expect.any(String) })
  })
  it('shows subscription tier and duration from the catalog', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.findAll('form')[0]!.find('select').setValue('2')
    expect(wrapper.findAll('output').map(item => item.text())).toEqual(['$30.00', 'USD', 'GOLD', '3'])
  })
  it('keeps monitoring usable when catalog loading fails and allows retry', async () => {
    api.mockImplementation((url: string) => url === '/api/admin/store-catalog' ? Promise.reject(new Error('Catalog offline')) : Promise.resolve(result))
    const wrapper = render(); await flushPromises()
    expect(wrapper.text()).toContain('dana')
    expect(wrapper.text()).toContain('Catalog offline')
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    api.mockImplementation((url: string) => Promise.resolve(url === '/api/admin/store-catalog' ? { items: [] } : result))
    await wrapper.find('button[type="button"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).not.toContain('Catalog offline')
    expect(wrapper.text()).toContain('No active paid products')
    expect(wrapper.find('a').attributes('to')).toBe('/transfers/catalog')
  })

  it('shows verified membership details, zero counts and translated system events', async () => {
    const data = { ...result, count: 1, status_counts: { draft: 0, pending: 0, paid: 1, failed: 0, cancelled: 0, refunded: 0 },
      items: [{ ...result.items[0], name: 'Quarterly Gold', product: 'subscription', tier: 'GOLD', period_months: 3,
        status: 'paid', paid_at: '2026-09-12T12:00:00Z', valid_until: '2026-12-12T12:00:00Z',
        events: [{ kind: 'payment_verified', actor: null, created_at: '2026-09-12T12:00:00Z' }] }] }
    api.mockImplementation((url: string) => Promise.resolve(url === '/api/admin/store-catalog' ? catalog : data))
    const wrapper = render(); await flushPromises()
    expect(wrapper.get('[data-testid="purchase-counts"]').text()).toContain('Paid: 1')
    expect(wrapper.text()).toContain('Pending: 0')
    expect(wrapper.text()).toContain('Quarterly Gold')
    expect(wrapper.text()).toContain('3 months')
    expect(wrapper.text()).toContain('Membership valid until')
    expect(wrapper.text()).toContain('Payment verified and purchase granted')
    expect(wrapper.text()).toContain('System')
  })

  it('refreshes empty purchases automatically and clears stale data on failure', async () => {
    vi.useFakeTimers()
    let data = { ...result, count: 0, items: [] as typeof result.items }
    api.mockImplementation((url: string) => Promise.resolve(url === '/api/admin/store-catalog' ? catalog : data))
    const wrapper = render(); await flushPromises()
    expect(wrapper.text()).not.toContain('dana')
    data = result
    await vi.advanceTimersByTimeAsync(30000); await flushPromises()
    expect(wrapper.text()).toContain('dana')
    api.mockRejectedValue(new Error('Offline'))
    await vi.advanceTimersByTimeAsync(30000); await flushPromises()
    expect(wrapper.text()).not.toContain('dana')
    expect(wrapper.get('[role="alert"]').text()).toContain('Offline')
    wrapper.unmount()
    api.mockClear()
    await vi.advanceTimersByTimeAsync(30000)
    expect(api).not.toHaveBeenCalled()
  })
})
