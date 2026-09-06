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

function mountPanel() {
  return mount(WalletAdjustmentPanel, {
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
    vi.clearAllMocks()
  })

  it('searches for a user and requires a returned selection', async () => {
    apiFetchMock.mockResolvedValueOnce([
      { id: 7, username: 'alice', email: 'alice@example.com', balance: '12.50' },
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
        { id: 7, username: 'alice', email: 'alice@example.com', balance: '12.50' },
      ])
      .mockResolvedValueOnce({
        id: 7,
        username: 'alice',
        email: 'alice@example.com',
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
        body: JSON.stringify({ action: 'deposit', amount: 25, note: 'Manual correction' }),
      })
    })
    expect(wrapper.emitted('adjusted')).toEqual([[{ userId: 7, action: 'deposit' }]])
    expect(wrapper.text()).toContain('37.50')
  })

  it('sends withdrawals as a wallet action', async () => {
    apiFetchMock
      .mockResolvedValueOnce([{ id: 9, username: 'bob', email: '', balance: '40.00' }])
      .mockResolvedValueOnce({ id: 9, username: 'bob', email: '', balance: '30.00' })
    const wrapper = mountPanel()

    await wrapper.get('[data-test="user-search"]').setValue('bob')
    await wrapper.get('[data-test="complete-search"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.suggestion').exists()).toBe(true))
    await wrapper.get('.suggestion').trigger('click')
    await wrapper.get('[data-test="amount"]').setValue('10')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === 'Withdraw')!
      .trigger('click')

    await vi.waitFor(() => {
      expect(apiFetchMock).toHaveBeenLastCalledWith('/api/admin/users/9/wallet', {
        method: 'POST',
        body: JSON.stringify({ action: 'withdraw', amount: 10, note: '' }),
      })
    })
  })
})
