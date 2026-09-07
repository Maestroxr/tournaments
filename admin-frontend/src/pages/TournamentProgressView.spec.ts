import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import PrimeVue from 'primevue/config'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TournamentProgressView from './TournamentProgressView.vue'
import TournamentMatchSummary from '@/components/tournament/TournamentMatchSummary.vue'
import TournamentMatchesPanel from '@/components/tournament/TournamentMatchesPanel.vue'
import TournamentFixtureCard from '@/components/TournamentFixtureCard.vue'
import TournamentLiveAttention from '@/components/tournament/TournamentLiveAttention.vue'
import TournamentLiveMatchGroup from '@/components/tournament/TournamentLiveMatchGroup.vue'
import TournamentBracketMatch from '@/components/tournament/TournamentBracketMatch.vue'
import TournamentMatchDialog from '@/components/tournament/TournamentMatchDialog.vue'
import { apiFetch, ApiError } from '@/services/api'
import { useI18n } from '@/i18n'
import type { TournamentFixture, TournamentProgressData } from '@/types/tournamentProgress'

vi.mock('@/services/api', async importOriginal => ({ ...await importOriginal<typeof import('@/services/api')>(), apiFetch: vi.fn() }))
const api = vi.mocked(apiFetch)
const player = { id: 1, user_id: 1, name: 'Dana', username: 'dana' }
const fixture = (id: number, extra: Partial<TournamentFixture> = {}): TournamentFixture => ({
  id, player1: player, player2: { ...player, id: 2, name: 'Ben' },
  score1: null, score2: null, is_confirmed: false, confirmations: 0, required_confirmations: 2,
  editable: false, has_confirmed: false, live: null, ...extra,
})
const playing = { status: 'playing', state: { phase: null, turn: null, dice: null, cube: 1 }, match_score: { white: 0, black: 0 } }
function progress(): TournamentProgressData {
  return {
    tournament: { id: 20, name: 'Club cup', state: 'active', participant_count: 6 },
    stages: { main_round: { levels: [{ fixtures: [fixture(1), fixture(2, { live: playing }), fixture(3, { is_confirmed: true, live: playing })] }] } },
    is_finished: false, podium: [],
  }
}
const close = vi.fn()
const Socket = vi.fn(class { close = close; onclose = null; onopen = null; onmessage = null; onerror = null })
let wrapper: ReturnType<typeof mount> | undefined
async function view(path = '/tournaments/20/live') {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/tournaments/:id/live', name: 'tournament-live', component: TournamentProgressView },
    { path: '/tournaments/:id/bracket', name: 'tournament-bracket', component: TournamentProgressView },
    { path: '/tournaments/:id/standings', name: 'tournament-standings', component: TournamentProgressView },
    { path: '/tournaments/:id/results', name: 'tournament-results', component: TournamentProgressView },
    { path: '/tournaments/:id/overview', name: 'tournament-detail', component: { template: '<div />' } },
    { path: '/tournaments', component: { template: '<div />' } },
  ] })
  await router.push(path)
  await router.isReady()
  wrapper = mount(TournamentProgressView, { global: { plugins: [router, PrimeVue] } })
  await flushPromises()
  return { wrapper, router }
}

describe('Tournament workspace', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal('WebSocket', Socket); useI18n().locale.value = 'en'; api.mockResolvedValue(progress()) })
  afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals() })

  it('shows a focused live page and counts only genuinely playing unconfirmed matches', async () => {
    const { wrapper } = await view()
    expect(wrapper.getComponent(TournamentMatchSummary).findAll('dd').map(n => n.text())).toEqual(['6', '1', '1', '0', '1'])
    expect(wrapper.findAllComponents(TournamentFixtureCard).map(c => c.props('fixture').id)).toEqual([2, 1, 3])
    expect(wrapper.text()).not.toContain('Minimum player count')
    expect(wrapper.text()).not.toContain('Entry fee')
  })

  it('prioritizes stalled matches, result reviews and players waiting for an opponent', async () => {
    const stalled = fixture(4, { operational_status: 'stalled', stalled: true, live: playing, round_name: 'Round 1' })
    const review = fixture(5, { operational_status: 'review', score1: 5, score2: 2, round_name: 'Round 1' })
    const waitingPlayer = fixture(6, { operational_status: 'waiting_opponent', player2: null, round_name: 'Round 1' })
    api.mockResolvedValue({
      ...progress(),
      stages: { main_round: { levels: [{ fixtures: [stalled, review, waitingPlayer] }] } },
      control_room: {
        current_stage: 'Main bracket', current_round: 'Round 1',
        counts: { playing: 0, waiting: 0, waiting_opponent: 1, review: 1, stalled: 1, completed: 0, upcoming: 0 },
        waiting_players: [{ id: 1, name: 'Dana', user_id: 1, fixture_id: 6, round_name: 'Round 1' }],
        round_total: 3, round_completed: 0, stale_after_seconds: 120, generated_at: new Date().toISOString(),
      },
    })

    const { wrapper } = await view()
    const attention = wrapper.getComponent(TournamentLiveAttention)
    expect(attention.props('stalled').map((item: TournamentFixture) => item.id)).toEqual([4])
    expect(attention.props('review').map((item: TournamentFixture) => item.id)).toEqual([5])
    expect(attention.props('waitingPlayers')).toHaveLength(1)
    expect(wrapper.text()).toContain('Resolve these before they delay the round')
    expect(wrapper.findAllComponents(TournamentLiveMatchGroup)).toHaveLength(4)
    expect(wrapper.getComponent(TournamentMatchSummary).text()).toContain('0 of 3 matches completed')
  })

  it('switches between bracket and standings routes without new API requests', async () => {
    const { wrapper, router } = await view()
    await router.push('/tournaments/20/bracket')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('tournament-bracket')
    expect(wrapper.findComponent(TournamentMatchesPanel).exists()).toBe(true)
    expect(wrapper.findComponent(TournamentMatchSummary).exists()).toBe(false)
    await router.push('/tournaments/20/standings')
    await flushPromises()
    expect(wrapper.text()).toContain('Final standings will appear once the tournament has finished.')
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('supports direct bracket links', async () => {
    const { wrapper } = await view('/tournaments/20/bracket')
    expect(wrapper.findAllComponents(TournamentBracketMatch)).toHaveLength(3)
  })

  it('opens the selected match dialog from its card and closes without mutating the game', async () => {
    api.mockImplementation(async path => String(path).endsWith('/matches/2') ? {
      fixture_id: 2, version: 'v1', note: '', can_rule: false, players: [],
      result: { score: [null, null], confirmed: false, winner_id: null, resolution: '' },
      times: { connection_created_at: null, live_started_at: null, ended_at: null }, history: [],
    } : progress())
    const { wrapper } = await view('/tournaments/20/bracket')
    expect(wrapper.findComponent(TournamentMatchDialog).exists()).toBe(false)
    await wrapper.findAllComponents(TournamentBracketMatch)[1]!.get('button').trigger('click')
    await flushPromises()
    const dialog = wrapper.getComponent(TournamentMatchDialog)
    expect(dialog.props('fixture').id).toBe(2)
    expect(api).toHaveBeenCalledTimes(2)
    expect(api).toHaveBeenLastCalledWith('/api/admin/tournaments/20/matches/2')
    dialog.vm.$emit('close')
    await flushPromises()
    expect(wrapper.findComponent(TournamentMatchDialog).exists()).toBe(false)
  })

  it('shows the actual final podium and does not open a live socket for a finished tournament', async () => {
    api.mockResolvedValue({ ...progress(), tournament: { ...progress().tournament, state: 'finished', lifecycle_state: 'finished' }, is_finished: true, podium: [{ id: 1, name: 'Winner Dana' }] })
    const { wrapper } = await view('/tournaments/20/results')
    expect(wrapper.text()).toContain('Winner Dana')
    expect(wrapper.text()).not.toContain('Periodic updates')
    expect(Socket).not.toHaveBeenCalled()
  })

  it('records organizer approval for final results', async () => {
    const finished = { ...progress(), tournament: { ...progress().tournament, state: 'finished', lifecycle_state: 'finished' }, is_finished: true, podium: [{ id: 1, name: 'Winner Dana' }] }
    api.mockImplementation(async (path, options) => {
      if (String(path).endsWith('/results/confirm') && options?.method === 'POST') {
        return { lifecycle_state: 'results_confirmed' }
      }
      return finished
    })
    vi.stubGlobal('confirm', vi.fn(() => true))
    const { wrapper } = await view('/tournaments/20/results')

    const approve = wrapper.findAll('button').find(button => button.text().includes('Approve final results'))!
    await approve.trigger('click')
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/tournaments/20/results/confirm', { method: 'POST' })
    expect(wrapper.text()).toContain('Final results approved')
  })

  it('routes not-yet-started tournaments back to setup', async () => {
    api.mockRejectedValue(new ApiError(412, '', 'Tournament has not started'))
    const { router } = await view()
    expect(router.currentRoute.value.path).toBe('/tournaments/20/overview')
    expect(Socket).not.toHaveBeenCalled()
  })

  it('cleans up its live connection when leaving', async () => {
    await view()
    wrapper!.unmount()
    wrapper = undefined
    expect(close).toHaveBeenCalledTimes(1)
  })
})
