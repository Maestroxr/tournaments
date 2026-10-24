import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import WalletTopUpDialog from './WalletTopUpDialog.vue'
import { apiFetch } from '@/services/api'

vi.mock('@/services/api', async (original) => ({
  ...await original<typeof import('@/services/api')>(),
  apiFetch: vi.fn(),
}))

const InputTextStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<input data-test="note" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
})

describe('WalletTopUpDialog', () => {
  it('retries a lost response with the same operation and resumes registration once', async () => {
    vi.mocked(apiFetch).mockReset()
    vi.mocked(apiFetch).mockRejectedValueOnce(new TypeError('Response lost'))
      .mockResolvedValueOnce({ balance: '25.00' })
    const wrapper = mount(WalletTopUpDialog, {
      props: { user: { id: 7, username: 'Player', balance: '0.00' }, entryFee: 25 },
      global: { stubs: {
        Dialog: { template: '<section><slot /></section>' },
        InputNumber: { template: '<input data-test="amount" />' },
        InputText: InputTextStub,
        Button: { props: ['label', 'type', 'disabled'], template: '<button :type="type" :disabled="disabled">{{ label }}</button>' },
        AppAlert: { props: ['message'], template: '<p>{{ message }}</p>' },
      } },
    })
    await wrapper.get('[data-test="note"]').setValue('Tournament top-up')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.emitted('saved')).toBeUndefined()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const bodies = vi.mocked(apiFetch).mock.calls.map((call) => JSON.parse(String(call[1]?.body)))
    expect(bodies).toHaveLength(2)
    expect(bodies[0]).toEqual({
      action: 'deposit', amount: 25, note: 'Tournament top-up', operation_id: expect.any(String),
    })
    expect(bodies[1]).toEqual(bodies[0])
    expect(wrapper.emitted('saved')).toEqual([['25.00']])
  })
})
