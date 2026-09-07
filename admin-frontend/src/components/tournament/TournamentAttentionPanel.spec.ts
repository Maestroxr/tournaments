import { mount, RouterLinkStub } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { useI18n } from '@/i18n'
import TournamentAttentionPanel from './TournamentAttentionPanel.vue'

describe('TournamentAttentionPanel', () => {
  it('shows a clear organizer state when there is nothing to resolve', () => {
    useI18n().locale.value = 'en'
    const wrapper = mount(TournamentAttentionPanel, { props: { items: [] } })

    expect(wrapper.text()).toContain('Nothing is blocking the next step')
    expect(wrapper.find('.attention-panel__count').exists()).toBe(false)
  })

  it('renders actionable issues with their severity and destination', () => {
    useI18n().locale.value = 'en'
    const wrapper = mount(TournamentAttentionPanel, {
      props: {
        items: [{
          id: 'players',
          title: 'Two players are still needed',
          detail: 'A minimum of six players is required.',
          action: 'Manage players',
          to: '/tournaments/20/players',
          severity: 'critical',
        }],
      },
      global: { stubs: { RouterLink: RouterLinkStub } },
    })

    expect(wrapper.get('.attention-item').classes()).toContain('attention-item--critical')
    expect(wrapper.getComponent(RouterLinkStub).props('to')).toBe('/tournaments/20/players')
    expect(wrapper.text()).toContain('Two players are still needed')
  })
})
