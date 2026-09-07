import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PrimeVue from 'primevue/config'
import Checkbox from 'primevue/checkbox'
import AddPlayerDialog from './AddPlayerDialog.vue'
import RosterRemovalDialog from './RosterRemovalDialog.vue'
import { useI18n } from '@/i18n'

const dialogStub = {
  template: '<section><header>{{ header }}</header><slot /><footer><slot name="footer" /></footer></section>',
  props: ['header'],
}

describe('attendee confirmation dialogs', () => {
  it('shows the exact wallet charge before adding a player', () => {
    useI18n().locale.value = 'en'
    const wrapper = mount(AddPlayerDialog, {
      props: { user: { id: 7, username: 'Dana', balance: '70.00' }, entryFee: 50 },
      global: { plugins: [PrimeVue], stubs: { Dialog: dialogStub } },
    })

    expect(wrapper.text()).toContain('Current wallet balance70.00')
    expect(wrapper.text()).toContain('Tournament entry fee−50.00')
    expect(wrapper.text()).toContain('Balance after registration20.00')
    wrapper.get('.p-button-success').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('defaults to crediting the paid entry fee and allows removing without it', async () => {
    useI18n().locale.value = 'en'
    const wrapper = mount(RosterRemovalDialog, {
      props: {
        players: [{ id: 11, name: 'Dana', refundable: '50.00' }],
        action: 'withdraw',
      },
      global: { plugins: [PrimeVue], stubs: { Dialog: dialogStub } },
    })

    expect(wrapper.text()).toContain('Credit 50.00 back to the wallet')
    expect(wrapper.getComponent(Checkbox).props('modelValue')).toBe(true)
    await wrapper.getComponent(Checkbox).setValue(false)
    await wrapper.get('.p-button-danger').trigger('click')
    expect(wrapper.emitted('confirm')).toEqual([[false]])
  })

  it('always uses the ordinary full entry-fee charge', async () => {
    useI18n().locale.value = 'en'
    const wrapper = mount(AddPlayerDialog, {
      props: {
        user: { id: 7, username: 'Dana', balance: '50.00' },
        entryFee: 50,
      },
      global: { plugins: [PrimeVue], stubs: { Dialog: dialogStub } },
    })

    expect(wrapper.text()).toContain('Tournament entry fee−50.00')
    expect(wrapper.text()).toContain('Charge and add player')
    expect(wrapper.findComponent(Checkbox).exists()).toBe(false)
    await wrapper.get('.p-button-success').trigger('click')
    expect(wrapper.emitted('confirm')).toEqual([[]])
  })

  it('offers the ordinary balance top-up when the full fee is not covered', async () => {
    useI18n().locale.value = 'en'
    const wrapper = mount(AddPlayerDialog, {
      props: {
        user: { id: 7, username: 'Dana', balance: '20.00' },
        entryFee: 50,
      },
      global: { plugins: [PrimeVue], stubs: { Dialog: dialogStub } },
    })

    expect(wrapper.text()).toContain('Insufficient balance')
    expect(wrapper.get('.p-button-success').attributes('disabled')).toBeDefined()
    await wrapper.get('.p-button-warn').trigger('click')
    expect(wrapper.emitted('topUp')).toEqual([[]])
  })
})
