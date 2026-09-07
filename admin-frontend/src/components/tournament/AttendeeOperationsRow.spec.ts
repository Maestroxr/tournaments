import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import PrimeVue from 'primevue/config'
import AttendeeOperationsRow from './AttendeeOperationsRow.vue'
import { useI18n } from '@/i18n'

const attendee = {
  id: 5,
  name: 'Dana',
  username: 'dana',
  user_id: 9,
  status: 'registered' as const,
  payment_status: 'unpaid' as const,
  checked_in_at: null,
  internal_note: '',
  requires_attention: true,
  attention_reasons: ['payment', 'check_in'],
  slot: 2,
}

function row(overrides = {}) {
  return mount(AttendeeOperationsRow, {
    props: {
      attendee: { ...attendee, ...overrides },
      selected: false,
      canChangeRoster: true,
      canPromote: true,
    },
    global: { plugins: [PrimeVue], stubs: { UserQuickView: true } },
  })
}

describe('AttendeeOperationsRow', () => {
  beforeEach(() => { useI18n().locale.value = 'en' })

  it('exposes operational status and emits focused actions', async () => {
    const wrapper = row()
    expect(wrapper.text()).toContain('Unpaid')
    expect(wrapper.text()).toContain('Not checked in')
    const buttons = wrapper.findAll('button')
    await buttons.find(button => button.text().includes('Check in'))!.trigger('click')
    expect(wrapper.emitted('action')?.[0]).toEqual(['check_in', [5]])
    await buttons.find(button => button.text().includes('Mark paid'))!.trigger('click')
    expect(wrapper.emitted('action')?.[1]).toEqual(['mark_paid', [5]])
  })

  it('offers promotion for a waitlisted player without check-in controls', () => {
    const wrapper = row({ status: 'waitlisted', payment_status: 'unpaid' })
    expect(wrapper.text()).toContain('Promote')
    expect(wrapper.text()).not.toContain('Check in')
  })
})
