import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import WalletTopUpDialog from './WalletTopUpDialog.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'

vi.mock('@/services/api', async (original) => ({
  ...await original<typeof import('@/services/api')>(),
  apiFetch: vi.fn(),
}))

const InputTextStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<input data-test="note" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
})

const api = vi.mocked(apiFetch)
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function dialog() {
  return mount(WalletTopUpDialog, {
    props: { user: { id: 7, username: 'Player', balance: '0.00' }, entryFee: 25 },
    global: { stubs: {
      Dialog: { template: '<section><slot /></section>' },
      InputNumber: { template: '<input data-test="amount" />' },
      InputText: InputTextStub,
      Button: { props: ['label', 'type', 'disabled'], template: '<button :type="type" :disabled="disabled">{{ label }}</button>' },
      AppAlert: { props: ['message'], template: '<p>{{ message }}</p>' },
    } },
  })
}

describe('WalletTopUpDialog', () => {
  beforeEach(() => { api.mockReset(); useI18n().locale.value = 'en' })

  it.each([
    ['empty', ''],
    ['whitespace-only', '   '],
    ['longer than 255 characters', 'x'.repeat(256)],
  ])('does not submit a note that is %s', async (_description, note) => {
    const wrapper = dialog()
    await wrapper.get('[data-test="note"]').setValue(note)
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api).not.toHaveBeenCalled()
    expect(wrapper.emitted('saved')).toBeUndefined()
  })

  it('retries a lost response with the same operation and resumes registration once', async () => {
    api.mockRejectedValueOnce(new TypeError('Response lost'))
      .mockResolvedValueOnce({ balance: '25.00' })
    const wrapper = dialog()
    await wrapper.get('[data-test="note"]').setValue('  Tournament top-up  ')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(wrapper.get('[data-test="amount"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="note"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const bodies = api.mock.calls.map((call) => JSON.parse(String(call[1]?.body)))
    expect(bodies).toHaveLength(2)
    expect(bodies[0]).toEqual({
      action: 'deposit', amount: 25, note: 'Tournament top-up', operation_id: expect.stringMatching(uuidPattern),
    })
    expect(bodies[1]).toEqual(bodies[0])
    expect(api.mock.calls[1]).toEqual(api.mock.calls[0])
    expect(wrapper.emitted('saved')).toEqual([['25.00']])
  })
})
