import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import WalletAdjustmentPanel from './WalletAdjustmentPanel.vue'
import { apiFetch } from '@/services/api'

vi.mock('@/services/api', () => ({
  apiFetch: vi.fn(),
  formatApiError: (error: unknown) => (error instanceof Error ? error.message : 'Request failed'),
}))

const apiFetchMock = vi.mocked(apiFetch)

const AutoCompleteStub = defineComponent({
  name: 'AutoComplete',
  props: {
    modelValue: { type: [Object, String], default: null },
    suggestions: { type: Array, default: () => [] },
  },
  emits: ['update:modelValue', 'complete'],
  setup(props, { emit }) {
    return () =>
      h('div', [
        h('input', {
          'data-test': 'user-search',
          value: typeof props.modelValue === 'string' ? props.modelValue : '',
          onInput: (event: Event) =>
            emit('update:modelValue', (event.target as HTMLInputElement).value),
        }),
        h(
          'button',
          {
            'data-test': 'complete-search',
            onClick: () =>
              emit('complete', {
                query: typeof props.modelValue === 'string' ? props.modelValue : '',
              }),
          },
          'Search users',
        ),
        ...props.suggestions.map((suggestion) =>
          h(
            'button',
            {
              class: 'suggestion',
              onClick: () => emit('update:modelValue', suggestion),
            },
            (suggestion as { username: string }).username,
          ),
        ),
      ])
  },
})

const InputNumberStub = defineComponent({
  name: 'InputNumber',
  props: { modelValue: { type: Number, default: null } },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () =>
      h('input', {
        'data-test': 'amount',
        type: 'number',
        value: props.modelValue ?? '',
        onInput: (event: Event) => {
          const value = (event.target as HTMLInputElement).value
          emit('update:modelValue', value ? Number(value) : null)
        },
      })
  },
})

const InputTextStub = defineComponent({
  name: 'InputText',
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () =>
      h('input', {
        'data-test': 'note',
        value: props.modelValue,
        onInput: (event: Event) =>
          emit('update:modelValue', (event.target as HTMLInputElement).value),
      })
  },
})

const ButtonStub = defineComponent({
  name: 'PrimeButtonStub',
  props: {
    label: { type: String, default: '' },
    disabled: { type: Boolean, default: false },
  },
  emits: ['click'],
  setup(props, { emit }) {
    return () =>
      h(
        'button',
        {
          disabled: props.disabled,
          onClick: () => emit('click'),
        },
        props.label,
      )
  },
})

function mountPanel(props: Record<string, unknown> = {}) {
  return mount(WalletAdjustmentPanel, {
    props,
    global: {
      stubs: {
        AutoComplete: AutoCompleteStub,
        InputNumber: InputNumberStub,
        InputText: InputTextStub,
        Button: ButtonStub,
        AppAlert: { props: ['message'], template: '<div>{{ message }}</div>' },
      },
    },
  })
}

async function selectUser(wrapper: ReturnType<typeof mountPanel>) {
  await wrapper.get('[data-test="user-search"]').setValue('alice')
  await wrapper.get('[data-test="complete-search"]').trigger('click')
  await vi.waitFor(() => expect(wrapper.find('.suggestion').exists()).toBe(true))
  await wrapper.get('.suggestion').trigger('click')
}

describe('WalletAdjustmentPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.clearAllMocks()
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('b09f9d21-1948-44f0-84a1-4556b11f596e')
  })

  it('searches for a user and requires a returned selection', async () => {
    apiFetchMock.mockResolvedValueOnce([
      { id: 7, username: 'alice', phone_number: '050-123-4567', balance: '12.50' },
    ])
    const wrapper = mountPanel()

    await wrapper.get('[data-test="user-search"]').setValue('alice & bob')
    await wrapper.get('[data-test="amount"]').setValue('10')
    await nextTick()
    const deposit = wrapper.findAll('button').find((button) => button.text() === 'Deposit')
    expect(deposit?.attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="complete-search"]').trigger('click')

    await vi.waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/admin/users?q=alice%20%26%20bob')
    })
  })

  it('deposits into the selected wallet and emits an adjustment', async () => {
    apiFetchMock
      .mockResolvedValueOnce([
        { id: 7, username: 'alice', phone_number: '050-123-4567', balance: '12.50' },
      ])
      .mockResolvedValueOnce({
        id: 7,
        username: 'alice',
        phone_number: '050-123-4567',
        balance: '37.50',
      })
    const wrapper = mountPanel()

    await selectUser(wrapper)
    await wrapper.get('[data-test="amount"]').setValue('25')
    await wrapper.get('[data-test="note"]').setValue('Manual correction')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === 'Deposit')!
      .trigger('click')

    await vi.waitFor(() => {
      expect(apiFetchMock).toHaveBeenLastCalledWith('/api/admin/users/7/wallet', {
        method: 'POST',
        body: JSON.stringify({ action: 'deposit', amount: 25, note: 'Manual correction', operation_id: 'b09f9d21-1948-44f0-84a1-4556b11f596e' }),
      })
    })
    expect(wrapper.emitted('adjusted')).toEqual([[{ userId: 7, action: 'deposit' }]])
    expect(wrapper.text()).toContain('37.50')
  })

  it('sends withdrawals as a wallet action', async () => {
    apiFetchMock
      .mockResolvedValueOnce([{ id: 9, username: 'bob', phone_number: '', balance: '40.00' }])
      .mockResolvedValueOnce({ id: 9, username: 'bob', phone_number: '', balance: '30.00' })
    const wrapper = mountPanel()

    await wrapper.get('[data-test="user-search"]').setValue('bob')
    await wrapper.get('[data-test="complete-search"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.suggestion').exists()).toBe(true))
    await wrapper.get('.suggestion').trigger('click')
    await wrapper.get('[data-test="amount"]').setValue('10')
    await wrapper.get('[data-test="note"]').setValue('Withdrawal request')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === 'Withdraw')!
      .trigger('click')

    await vi.waitFor(() => {
      expect(apiFetchMock).toHaveBeenLastCalledWith('/api/admin/users/9/wallet', {
        method: 'POST',
        body: JSON.stringify({ action: 'withdraw', amount: 10, note: 'Withdrawal request', operation_id: 'b09f9d21-1948-44f0-84a1-4556b11f596e' }),
      })
    })
  })

  it('uses a preset user and only offers deposits when requested', async () => {
    apiFetchMock.mockResolvedValueOnce({
      id: 12,
      username: 'dana',
      phone_number: '',
      balance: '25.00',
    })
    const wrapper = mountPanel({
      user: { id: 12, username: 'dana', phone_number: '', balance: '0.00' },
      depositOnly: true,
    })

    expect(wrapper.find('[data-test="user-search"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Add funds to dana')
    expect(wrapper.text()).not.toContain('Withdraw')

    await wrapper.get('[data-test="amount"]').setValue('25')
    await wrapper.get('[data-test="note"]').setValue('Opening deposit')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === 'Deposit')!
      .trigger('click')

    await vi.waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/admin/users/12/wallet', {
        method: 'POST',
        body: JSON.stringify({ action: 'deposit', amount: 25, note: 'Opening deposit', operation_id: 'b09f9d21-1948-44f0-84a1-4556b11f596e' }),
      })
    })
  })
  it('rejects a whitespace-only note without sending an adjustment', async () => {
    const wrapper = mountPanel({ user: { id: 12, username: 'dana', phone_number: '', balance: '0.00' } })
    await wrapper.get('[data-test="amount"]').setValue('25')
    await wrapper.get('[data-test="note"]').setValue('   ')
    await wrapper.findAll('button').find(button => button.text() === 'Deposit')!.trigger('click')
    expect(apiFetchMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Enter a reason for this adjustment.')
  })

  it('reuses the operation after a lost response and creates a new one after success', async () => {
    const user = { id: 12, username: 'dana', phone_number: '', balance: '25.00' }
    vi.mocked(crypto.randomUUID)
      .mockReturnValueOnce('b09f9d21-1948-44f0-84a1-4556b11f596e')
      .mockReturnValueOnce('fd841b1b-6d2c-4c68-943a-702ed128f08a')
    apiFetchMock.mockRejectedValueOnce(new TypeError('Response lost'))
      .mockResolvedValueOnce(user).mockResolvedValueOnce(user)
    const wrapper = mountPanel({ user })
    const deposit = () => wrapper.findAll('button').find(button => button.text() === 'Deposit')!
    await wrapper.get('[data-test="amount"]').setValue('25')
    await wrapper.get('[data-test="note"]').setValue('Verified correction')
    await deposit().trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Response lost'))
    await deposit().trigger('click')
    await vi.waitFor(() => expect(wrapper.emitted('adjusted')).toHaveLength(1))
    expect(apiFetchMock.mock.calls[0]?.[1]?.body).toBe(apiFetchMock.mock.calls[1]?.[1]?.body)
    await wrapper.get('[data-test="amount"]').setValue('25')
    await wrapper.get('[data-test="note"]').setValue('Verified correction')
    await deposit().trigger('click')
    await vi.waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(3))
    expect(JSON.parse(String(apiFetchMock.mock.calls[2]?.[1]?.body)).operation_id)
      .toBe('fd841b1b-6d2c-4c68-943a-702ed128f08a')
  })
})
