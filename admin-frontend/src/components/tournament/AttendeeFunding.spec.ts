import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PrimeVue from 'primevue/config'
import AttendeeUserRow from './AttendeeUserRow.vue'
import WalletTopUpDialog from './WalletTopUpDialog.vue'
import UserQuickView from '@/components/UserQuickView.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(), apiFetch: vi.fn(),
}))
const api = vi.mocked(apiFetch)
const user = { id: 7, username: 'Dana', balance: '20.00' }
const global = { plugins: [PrimeVue], stubs: { UserQuickView: true } }

describe('Attendee funding', () => {
  beforeEach(() => { vi.clearAllMocks(); useI18n().locale.value = 'en' })

  it('blocks paid registration with insufficient funds and offers a top-up', async () => {
    const wrapper = mount(AttendeeUserRow, { props: { user, entryFee: 50 }, global })
    expect(wrapper.getComponent(UserQuickView).props()).toMatchObject({ userId: 7, username: 'Dana' })
    expect(wrapper.findAll('button')).toHaveLength(2)
    expect(wrapper.get('[aria-label="Add Dana"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('30')
    await wrapper.get('[aria-label="Add balance for Dana"]').trigger('click')
    expect(wrapper.emitted('topUp')).toHaveLength(1)
    expect(wrapper.emitted('add')).toBeUndefined()
  })

  it('allows adding after the balance is refreshed', async () => {
    const wrapper = mount(AttendeeUserRow, { props: { user, entryFee: 50 }, global })
    await wrapper.setProps({ user: { ...user, balance: '50.00' } })
    await wrapper.get('[aria-label="Add Dana"]').trigger('click')
    expect(wrapper.emitted('add')).toEqual([[7]])
    expect(wrapper.findAll('button')).toHaveLength(1)
  })

  it('blocks unknown paid balances but still permits free entry', async () => {
    const wrapper = mount(AttendeeUserRow, { props: { user: { ...user, balance: null }, entryFee: 50 }, global })
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ entryFee: 0 })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('add')).toEqual([[7]])
  })

  function dialog() {
    return mount(WalletTopUpDialog, {
      props: { user, entryFee: 50 },
      global: { ...global, stubs: { Dialog: { template: '<div><slot /></div>' } } },
    })
  }

  it('prefills the shortfall, waits for confirmation, and only deposits once', async () => {
    let resolve!: (value: unknown) => void
    api.mockImplementation(() => new Promise(done => { resolve = done }))
    const wrapper = dialog()
    expect(wrapper.get('input').element.value).toBe('30')
    expect(api).not.toHaveBeenCalled()
    await wrapper.get('form').trigger('submit')
    await wrapper.get('form').trigger('submit')
    expect(api).toHaveBeenCalledTimes(1)
    expect(api).toHaveBeenCalledWith('/api/admin/users/7/wallet', {
      method: 'POST', body: JSON.stringify({ action: 'deposit', amount: 30, note: '' }),
    })
    resolve({ balance: '50.00' })
    await flushPromises()
    expect(wrapper.emitted('saved')).toEqual([['50.00']])
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('does not retry an uncertain deposit or emit success', async () => {
    api.mockRejectedValue(new TypeError('Connection lost'))
    const wrapper = dialog()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper.get('form').trigger('submit')
    expect(api).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('saved')).toBeUndefined()
  })
})
