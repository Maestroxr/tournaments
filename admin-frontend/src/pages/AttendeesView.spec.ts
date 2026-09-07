import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PrimeVue from 'primevue/config'
import AttendeesView from './AttendeesView.vue'
import AttendeeUserRow from '@/components/tournament/AttendeeUserRow.vue'
import WalletTopUpDialog from '@/components/tournament/WalletTopUpDialog.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { id: 20 } }) }))
vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(), apiFetch: vi.fn(),
}))
const api = vi.mocked(apiFetch)
const response = (balance: string | undefined = '20.00') => ({
  participants: [], available: [{ id: 7, username: 'Dana', balance }],
  tournament: { state: 'open', entry_fee: '50.00', max_players: 8 },
})
function view() {
  return mount(AttendeesView, {
    global: { plugins: [PrimeVue], stubs: { RouterLink: true, WalletTopUpDialog: true, UserQuickView: true } },
  })
}

describe('AttendeesView', () => {
  beforeEach(() => { vi.clearAllMocks(); useI18n().locale.value = 'en' })

  it('removes guest creation and opens the selected player balance dialog', async () => {
    api.mockResolvedValue(response())
    const wrapper = view()
    await flushPromises()
    expect(wrapper.findAll('input')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('Add guest')
    expect(wrapper.findComponent(WalletTopUpDialog).exists()).toBe(false)
    wrapper.getComponent(AttendeeUserRow).vm.$emit('topUp')
    await flushPromises()
    expect(wrapper.getComponent(WalletTopUpDialog).props('user').id).toBe(7)
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('refreshes the balance after a deposit without registering automatically', async () => {
    api.mockResolvedValueOnce(response()).mockResolvedValueOnce(response('50.00'))
    const wrapper = view()
    await flushPromises()
    wrapper.getComponent(AttendeeUserRow).vm.$emit('topUp')
    await flushPromises()
    wrapper.getComponent(WalletTopUpDialog).vm.$emit('saved', '50.00')
    await flushPromises()
    expect(wrapper.findComponent(WalletTopUpDialog).exists()).toBe(false)
    expect(wrapper.getComponent(AttendeeUserRow).props('user').balance).toBe('50.00')
    expect(wrapper.get('[aria-label="Add Dana"]').attributes('disabled')).toBeUndefined()
    expect(api.mock.calls.every(call => call[1]?.method !== 'POST')).toBe(true)
  })

  it('loads balances from the staff user API for a legacy running server', async () => {
    const legacy = { ...response(), available: [{ id: 7, username: 'Dana' }] }
    api.mockResolvedValueOnce(legacy).mockResolvedValueOnce([{ id: 7, balance: '60.00' }])
    const wrapper = view()
    await flushPromises()
    expect(api).toHaveBeenLastCalledWith('/api/admin/users')
    expect(wrapper.getComponent(AttendeeUserRow).props('user').balance).toBe('60.00')
  })

  it('shows readiness metrics and runs a bulk check-in for selected players', async () => {
    const operational = {
      participants: [{
        id: 11, name: 'Dana', username: 'Dana', user_id: 7, status: 'registered',
        payment_status: 'paid', checked_in_at: null, internal_note: '', disqualified: false,
        requires_attention: true, attention_reasons: ['check_in'], slot: 1,
      }],
      available: [],
      summary: { registered: 1, checked_in: 0, unpaid: 0, waitlisted: 0, attention: 1, ready: 0 },
      tournament: { state: 'open', registration_open: true, entry_fee: '50.00', max_players: 8 },
    }
    api.mockResolvedValueOnce(operational).mockResolvedValueOnce({}).mockResolvedValueOnce({
      ...operational,
      participants: [{ ...operational.participants[0], checked_in_at: '2026-09-07T12:00:00Z', requires_attention: false, attention_reasons: [] }],
      summary: { ...operational.summary, checked_in: 1, attention: 0, ready: 1 },
    })
    const wrapper = view()
    await flushPromises()
    expect(wrapper.text()).toContain('Requires attention')
    await wrapper.get('.select-visible input').setValue(true)
    await wrapper.get('.bulk-bar .p-button-success').trigger('click')
    await flushPromises()
    expect(api).toHaveBeenCalledWith('/api/admin/tournaments/20/attendees', expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ participant_ids: [11], action: 'check_in' }),
    }))
    expect(wrapper.text()).toContain('1/1')
  })
})
