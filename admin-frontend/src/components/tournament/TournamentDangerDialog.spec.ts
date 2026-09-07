import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import PrimeVue from 'primevue/config'
import TournamentDangerDialog from './TournamentDangerDialog.vue'
import { useI18n } from '@/i18n'

const dialogStub = {
  template: '<section><header>{{ header }}</header><slot /><footer><slot name="footer" /></footer></section>',
  props: ['header'],
}

describe('TournamentDangerDialog', () => {
  afterEach(() => { useI18n().locale.value = 'en' })
  it('explains the destructive effects before returning to draft', async () => {
    useI18n().locale.value = 'he'
    const wrapper = mount(TournamentDangerDialog, {
      props: { mode: 'revert', name: 'אליפות המועדון', entryFee: '50.00' },
      global: { plugins: [PrimeVue], stubs: { Dialog: dialogStub } },
    })

    expect(wrapper.text()).toContain('להחזיר את הטורניר לטיוטה?')
    expect(wrapper.text()).toContain('הסרת כל השחקנים וההרשמות')
    expect(wrapper.text()).toContain('זיכוי דמי הכניסה')
    await wrapper.get('.p-button-danger').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('does not mention refunds for a free tournament', () => {
    const wrapper = mount(TournamentDangerDialog, {
      props: { mode: 'revert', name: 'Free cup', entryFee: '0.00' },
      global: { plugins: [PrimeVue], stubs: { Dialog: dialogStub } },
    })

    expect(wrapper.text()).toContain('Remove all players and registrations')
    expect(wrapper.text()).not.toContain('Credit paid entry fees')
  })
})
