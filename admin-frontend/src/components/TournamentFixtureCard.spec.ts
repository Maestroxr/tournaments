import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TournamentFixtureCard from './TournamentFixtureCard.vue'
import UserQuickView from './UserQuickView.vue'
import type { TournamentFixture } from '@/types/tournamentProgress'

const fixture: TournamentFixture = {
  id: 12,
  player1: { id: 1, user_id: 101, name: 'Dana Cohen', username: 'dana' },
  player2: { id: 2, user_id: 102, name: 'Ben Levi', username: 'ben' },
  score1: null,
  score2: null,
  confirmations: 0,
  is_confirmed: false,
  required_confirmations: 2,
  editable: true,
  has_confirmed: false,
  live: null,
}

function mountCard(overrides: Partial<TournamentFixture> = {}) {
  return mount(TournamentFixtureCard, {
    props: { fixture: { ...fixture, ...overrides } },
    global: { stubs: { UserQuickView: true } },
  })
}

describe('TournamentFixtureCard', () => {
  it('uses the existing user quick view for both players', () => {
    const wrapper = mountCard()
    const users = wrapper.findAllComponents(UserQuickView)

    expect(users).toHaveLength(2)
    expect(users.map((user) => user.props())).toEqual([
      expect.objectContaining({ userId: 101, username: 'Dana Cohen' }),
      expect.objectContaining({ userId: 102, username: 'Ben Levi' }),
    ])
    expect(wrapper.text()).toContain('@dana')
    expect(wrapper.text()).toContain('@ben')
  })

  it('shows an informative waiting state when no score is available', () => {
    const wrapper = mountCard()

    expect(wrapper.classes()).toContain('fixture-card--waiting')
    expect(wrapper.get('.fixture-card__divider').text()).toBe('VS')
    expect(wrapper.text()).toContain('Waiting for the final score')
    expect(wrapper.text()).toContain('Match details')
  })

  it('opens match management from the primary action', async () => {
    const wrapper = mountCard()

    await wrapper.get('.fixture-card__admin').trigger('click')

    expect(wrapper.emitted('select')).toEqual([[12]])
  })

  it('highlights the winner and displays confirmation details', () => {
    const wrapper = mountCard({ score1: 5, score2: 2, confirmations: 2, is_confirmed: true })

    expect(wrapper.classes()).toContain('fixture-card--confirmed')
    expect(wrapper.findAll('.is-winner')).toHaveLength(1)
    expect(wrapper.findAll('.fixture-card__player-score').map((score) => score.text())).toEqual([
      '5',
      '2',
    ])
    expect(wrapper.text()).toContain('Result is locked into the bracket')
  })

  it('surfaces live match details', () => {
    const wrapper = mountCard({
      live: {
        status: 'playing',
        state: { phase: 'moving', turn: 'white', dice: [4, 2], cube: 2 },
        match_score: { white: 3, black: 1 },
      },
    })

    expect(wrapper.classes()).toContain('fixture-card--playing')
    expect(wrapper.get('.fixture-card__live-stats').text()).toContain('3 : 1')
    expect(wrapper.get('.fixture-card__live-stats').text()).toContain('white')
    expect(wrapper.get('.fixture-card__live-stats').text()).toContain('2')
  })

  it('prioritizes a stalled warning and shows elapsed time', () => {
    const wrapper = mountCard({
      operational_status: 'stalled',
      stalled: true,
      started_at: '2026-09-07T12:00:00Z',
      duration_seconds: 754,
      live: {
        status: 'playing',
        state: { phase: 'moving', turn: 'white', dice: null, cube: 1 },
        match_score: { white: 1, black: 0 },
      },
    })

    expect(wrapper.classes()).toContain('fixture-card--stalled')
    expect(wrapper.get('.fixture-card__timing').text()).toContain('12:34')
    expect(wrapper.text()).toContain('No recent activity')
  })
})
