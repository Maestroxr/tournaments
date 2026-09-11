import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PrimeVue from 'primevue/config'
import SelectButton from 'primevue/selectbutton'
import FinancialOverviewView from './FinancialOverviewView.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(), apiFetch: vi.fn(),
}))

const api = vi.mocked(apiFetch)
const response = {
  updated_at: '2026-09-07T12:00:00Z',
  range_days: 30,
  currency: 'COINS',
  summary: {
    revenue: '1000.00', refunds: '100.00', prizes: '300.00', expenses: '400.00',
    net: '600.00', outstanding: '150.00', outstanding_count: 3,
  },
  trend: [
    { date: '2026-09-05', revenue: '200.00', expenses: '0.00', net: '200.00' },
    { date: '2026-09-06', revenue: '300.00', expenses: '100.00', net: '200.00' },
    { date: '2026-09-07', revenue: '500.00', expenses: '300.00', net: '200.00' },
  ],
  tournaments: [{
    id: 4, name: 'Open Tel Aviv', revenue: '1000.00', refunds: '100.00',
    prizes: '300.00', expenses: '400.00', net: '600.00',
  }],
  ignored_transactions: 0,
}

function view() {
  return mount(FinancialOverviewView, {
    global: {
      plugins: [PrimeVue],
      stubs: { RouterLink: { props: ['to'], template: '<a :data-to="to"><slot /></a>' } },
    },
  })
}

describe('FinancialOverviewView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useI18n().locale.value = 'en'
    api.mockResolvedValue(response)
  })

  it('renders the financial summary, trend and tournament comparison', async () => {
    const wrapper = view()
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/finance?days=30')
    expect(wrapper.text()).toContain('Entry-fee revenue')
    expect(wrapper.text()).toContain('1,000 coins')
    expect(wrapper.text()).toContain('Tournament net')
    expect(wrapper.text()).toContain('600 coins')
    expect(wrapper.text()).toContain('3 unpaid registrations, as of now')
    expect(wrapper.findAll('.finance-chart__line')).toHaveLength(3)
    expect(wrapper.text()).toContain('Open Tel Aviv')
    expect(wrapper.find('a').attributes('data-to')).toBe('/tournaments/4/overview')
  })

  it('reloads for a different reporting period', async () => {
    const wrapper = view()
    await flushPromises()

    wrapper.getComponent(SelectButton).vm.$emit('update:modelValue', 90)
    await flushPromises()

    expect(api).toHaveBeenLastCalledWith('/api/admin/finance?days=90')
  })

  it('warns when malformed ledger entries were excluded', async () => {
    api.mockResolvedValue({ ...response, ignored_transactions: 2 })
    const wrapper = view()
    await flushPromises()

    expect(wrapper.text()).toContain('2 transactions with an unexpected sign')
  })
})
