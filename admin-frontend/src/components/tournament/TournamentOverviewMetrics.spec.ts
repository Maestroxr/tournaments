import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { useI18n } from '@/i18n'
import TournamentOverviewMetrics from './TournamentOverviewMetrics.vue'

describe('TournamentOverviewMetrics', () => {
  it('renders the organizer snapshot and metric tone', () => {
    useI18n().locale.value = 'en'
    const wrapper = mount(TournamentOverviewMetrics, {
      props: {
        metrics: [{
          id: 'registration',
          label: 'Registration',
          value: '6/8',
          hint: 'Minimum reached',
          icon: 'bi-people',
          tone: 'good',
        }],
      },
    })

    expect(wrapper.get('section').attributes('aria-label')).toBe('Tournament snapshot')
    expect(wrapper.get('.overview-metric').classes()).toContain('overview-metric--good')
    expect(wrapper.text()).toContain('6/8')
  })
})
