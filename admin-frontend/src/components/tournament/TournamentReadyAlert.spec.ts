import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PrimeVue from 'primevue/config'
import TournamentActionCard from './TournamentActionCard.vue'
import TournamentReadyAlert from './TournamentReadyAlert.vue'
import { useI18n } from '@/i18n'

describe('TournamentReadyAlert', () => {
  it('announces readiness and starts from the current page', async () => {
    useI18n().locale.value = 'en'
    const wrapper = mount(TournamentReadyAlert, {
      props: { participantCount: 6, minPlayers: 6 },
      global: {
        plugins: [PrimeVue],
      },
    })

    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.attributes('aria-live')).toBe('polite')
    expect(wrapper.text()).toContain('Ready for the first round')
    expect(wrapper.text()).toContain('6')
    expect(wrapper.getComponent(TournamentActionCard).props()).toMatchObject({
      label: 'Start tournament',
      tone: 'green',
    })
    expect(wrapper.getComponent(TournamentActionCard).props('to')).toBeUndefined()

    wrapper.getComponent(TournamentActionCard).vm.$emit('activate')
    expect(wrapper.emitted('start')).toHaveLength(1)
  })
})
