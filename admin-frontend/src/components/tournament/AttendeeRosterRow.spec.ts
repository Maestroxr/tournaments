import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PrimeVue from 'primevue/config'
import AttendeeRosterRow from './AttendeeRosterRow.vue'

const attendee = {
  id: 11,
  name: 'Dana',
  username: 'Dana',
  user_id: 7,
  status: 'registered' as const,
  payment_status: 'paid' as const,
  refundable: '50.00',
}

describe('AttendeeRosterRow', () => {
  it('keeps the roster row focused on identity and removal', async () => {
    const wrapper = mount(AttendeeRosterRow, {
      props: { attendee, removable: true },
      global: { plugins: [PrimeVue], stubs: { UserQuickView: true } },
    })

    expect(wrapper.text()).toContain('Remove attendee')
    expect(wrapper.text()).not.toContain('Paid')
    expect(wrapper.find('input').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('remove')).toEqual([[11]])
  })

  it('shows no actions once roster changes are locked', () => {
    const wrapper = mount(AttendeeRosterRow, {
      props: { attendee, removable: false },
      global: { plugins: [PrimeVue], stubs: { UserQuickView: true } },
    })

    expect(wrapper.find('button').exists()).toBe(false)
  })
})
