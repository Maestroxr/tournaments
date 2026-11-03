import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Drawer from 'primevue/drawer'
import TournamentMatchAdminPanel from './TournamentMatchAdminPanel.vue'
import MatchAdjudicationNotice from './MatchAdjudicationNotice.vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TournamentMatchDialog from './TournamentMatchDialog.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'
import type { TournamentFixture } from '@/types/tournamentProgress'
import type { MatchAdministration } from '@/types/matchAdministration'

vi.mock('@/services/api', async (original) => ({
  ...(await original<typeof import('@/services/api')>()),
  apiFetch: vi.fn(),
}))
const api = vi.mocked(apiFetch)
function fixture(extra: Partial<TournamentFixture> = {}): TournamentFixture {
  return {
    id: 12,
    player1: { id: 1, user_id: 1, name: 'Dana', username: 'dana' },
    player2: { id: 2, user_id: 2, name: 'Ben', username: 'ben' },
    score1: null,
    score2: null,
    confirmations: 0,
    required_confirmations: 2,
    is_confirmed: false,
    editable: true,
    has_confirmed: false,
    live: null,
    can_play: true,
    ...extra,
  }
}
function incidentFixture(extra: Partial<TournamentFixture> = {}): TournamentFixture {
  return fixture({
    live: {
      status: 'playing',
      event_revision: 2,
      event_type: 'admin_required',
      occurred_at: '2026-11-02T12:01:00Z',
      state: {
        phase: 'moving',
        turn: 'white',
        dice: [3, 6],
        cube: 2,
        presence: {
          needsAdminAdjudication: true,
          absentSince: { white: 1793620800, black: 1793620860 },
        },
      },
      match_score: { white: 2, black: 1 },
    },
    ...extra,
  })
}
function administration(extra: Partial<MatchAdministration> = {}): MatchAdministration {
  return {
    fixture_id: 12,
    version: 'v1',
    note: '',
    can_rule: true,
    target_points: 5,
    needs_admin_adjudication: true,
    absent_since: {},
    players: [],
    history: [],
    result: { score: [null, null], confirmed: false, winner_id: null, resolution: '' },
    times: { connection_created_at: null, live_started_at: null, ended_at: null },
    ...extra,
  }
}
const wrappers: ReturnType<typeof mount>[] = []
function view(
  value = fixture(),
  extra: { tournamentId?: string; liveConnected?: boolean; updatedAt?: Date } = {},
) {
  const wrapper = mount(TournamentMatchDialog, {
    props: { fixture: value, round: 'Semifinals', ...extra },
    global: {
      plugins: [PrimeVue],
      stubs: {
        Drawer: {
          props: ['position', 'dismissable', 'showCloseIcon', 'closeOnEscape'],
          template: '<div><slot /><slot name="footer" /></div>',
        },
        TournamentMatchAdminPanel: {
          props: ['section', 'action'],
          template: '<div />',
          emits: ['busy', 'saved', 'loaded', 'update:action'],
        },
      },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

describe('Admin match details dialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useI18n().locale.value = 'en'
  })
  afterEach(() => {
    wrappers.splice(0).forEach((w) => w.unmount())
  })

  it('opens on live status and uses buttons to show one tool without remounting drafts', async () => {
    const wrapper = view(fixture(), { tournamentId: '20' })
    const panel = wrapper.getComponent(TournamentMatchAdminPanel)
    const instance = panel.vm
    expect(panel.isVisible()).toBe(false)
    expect(wrapper.get('.match-live').isVisible()).toBe(true)
    expect(wrapper.findAll('[data-section]')).toHaveLength(6)
    for (const section of ['score', 'players', 'times', 'note', 'history']) {
      await wrapper.get(`[data-section="${section}"]`).trigger('click')
      expect(panel.props('section')).toBe(section)
      expect(panel.isVisible()).toBe(true)
      expect(wrapper.get('.match-live').isVisible()).toBe(false)
      expect(wrapper.get(`[data-section="${section}"]`).attributes('aria-pressed')).toBe('true')
    }
    await wrapper.get('[data-section="live"]').trigger('click')
    expect(panel.isVisible()).toBe(false)
    expect(wrapper.get('.match-live').isVisible()).toBe(true)
    expect(wrapper.getComponent(TournamentMatchAdminPanel).vm).toBe(instance)
    expect(api).not.toHaveBeenCalled()
  })

  it('shows provisional live scores separately and updates with new props', async () => {
    const wrapper = view(
      fixture({
        live: {
          status: 'playing',
          state: { turn: 'white', phase: null, dice: null, cube: 1 },
          match_score: { white: 2, black: 1 },
        },
      }),
    )
    expect(wrapper.get('.match-live').text()).toContain('2 : 1')
    expect(wrapper.get('.match-live').text()).toContain('White')
    expect(wrapper.text()).toContain('The game is in progress.')
    await wrapper.setProps({ fixture: fixture({ is_confirmed: true, score1: 5, score2: 1 }) })
    expect(wrapper.find('.match-live').exists()).toBe(false)
    expect(wrapper.findAll('.match-dialog__player strong').map((n) => n.text())).toEqual(['5', '1'])
  })

  it('explains future rounds without checking the administrator’s player permissions', () => {
    const wrapper = view(fixture({ editable: false, can_play: false }))
    expect(wrapper.text()).toContain('when its round starts')
  })

  it('uses a full-height drawer at the reading-direction edge', async () => {
    const wrapper = view()
    expect(wrapper.getComponent(Drawer).props('position')).toBe('right')
    expect(wrapper.getComponent(Drawer).props('dismissable')).toBe(false)
    expect(wrapper.getComponent(Drawer).attributes('style')).toContain('100dvh')
    useI18n().locale.value = 'he'
    await wrapper.vm.$nextTick()
    expect(wrapper.getComponent(Drawer).props('position')).toBe('left')
    expect(wrapper.getComponent(Drawer).attributes('dir')).toBe('rtl')
  })

  it('updates live details without recreating organizer controls', async () => {
    const live = {
      status: 'playing',
      state: { turn: 'white', phase: null, dice: [3, 6], cube: 2 },
      match_score: { white: 2, black: 1 },
    }
    const wrapper = view(fixture({ live }), { tournamentId: '20', liveConnected: true })
    const panel = wrapper.getComponent(TournamentMatchAdminPanel).vm
    expect(wrapper.get('.match-live').text()).toContain('Live feed connected')
    expect(wrapper.findAll('.match-live dd').map((n) => n.text())).toEqual(['White', '3 · 6', '2'])
    await wrapper.setProps({
      fixture: fixture({
        live: {
          ...live,
          state: { ...live.state, turn: 'black' },
          match_score: { white: 3, black: 1 },
        },
      }),
      liveConnected: false,
    })
    expect(wrapper.get('.match-live').text()).toContain('3 : 1')
    expect(wrapper.get('.match-live').text()).toContain('Periodic updates')
    expect(wrapper.getComponent(TournamentMatchAdminPanel).vm).toBe(panel)
  })

  it('shows an honest empty state before receiving live data', () => {
    const wrapper = view()
    expect(wrapper.text()).toContain('No live game data has been received yet')
    expect(wrapper.find('.match-live__score').exists()).toBe(false)
  })

  it('shows an admin event without frozen scores, dice or turn', () => {
    const wrapper = view(incidentFixture())
    expect(wrapper.get('.match-live').text()).toContain('Game status')
    expect(wrapper.get('[data-testid="match-adjudication"]').text().toLowerCase()).toContain(
      'no winner was selected automatically',
    )
    expect(wrapper.get('[data-testid="match-dialog-status"]').text()).toBe(
      'Awaiting administrator decision',
    )
    expect(wrapper.find('.match-live__score').exists()).toBe(false)
    expect(wrapper.get('.match-live').text()).not.toContain('Doubling cube')
    expect(wrapper.get('.match-live').text()).not.toContain('Dice')
  })

  it.each([
    ['finish', 'score'],
    ['advance', 'players'],
    ['disqualify', 'players'],
  ] as const)(
    'opens the %s ruling form directly without deciding the match',
    async (action, section) => {
      const wrapper = view(incidentFixture(), { tournamentId: '20' })
      const panel = wrapper.getComponent(TournamentMatchAdminPanel)
      const instance = panel.vm
      panel.vm.$emit('loaded', administration())
      await wrapper.vm.$nextTick()

      await wrapper.get(`[data-incident-action="${action}"]`).trigger('click')

      expect(panel.props('section')).toBe(section)
      expect(panel.props('action')).toBe(action)
      expect(panel.isVisible()).toBe(true)
      expect(wrapper.getComponent(TournamentMatchAdminPanel).vm).toBe(instance)
      expect(api).not.toHaveBeenCalled()
    },
  )

  it('reselects the requested ruling after another player action and preserves the panel instance', async () => {
    const wrapper = view(incidentFixture(), { tournamentId: '20' })
    const panel = wrapper.getComponent(TournamentMatchAdminPanel)
    panel.vm.$emit('loaded', administration())
    await wrapper.vm.$nextTick()
    await wrapper.get('[data-incident-action="advance"]').trigger('click')
    panel.vm.$emit('update:action', 'disqualify')
    await wrapper.vm.$nextTick()
    await wrapper.get('[data-section="live"]').trigger('click')
    await wrapper.get('[data-incident-action="advance"]').trigger('click')
    expect(panel.props('action')).toBe('advance')
    expect(panel.props('section')).toBe('players')
    expect(api).not.toHaveBeenCalled()
  })

  it('keeps history available for a locked match but blocks every shortcut while a write is pending', async () => {
    const wrapper = view(incidentFixture(), { tournamentId: '20' })
    const panel = wrapper.getComponent(TournamentMatchAdminPanel)
    panel.vm.$emit('loaded', administration({ can_rule: false }))
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-incident-action="finish"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-incident-action="history"]').trigger('click')
    expect(panel.props('section')).toBe('history')
    await wrapper.get('[data-section="live"]').trigger('click')
    panel.vm.$emit('busy', true)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-incident-action="history"]').attributes('disabled')).toBeDefined()
    wrapper.getComponent(MatchAdjudicationNotice).vm.$emit('action', 'history')
    await wrapper.vm.$nextTick()
    expect(panel.props('section')).toBe('live')
    expect(api).not.toHaveBeenCalled()
  })

  it.each([
    { is_confirmed: true },
    { admin_resolution: 'advance' },
    { operational_status: 'completed' as const },
  ])('removes the incident after a terminal fixture update: %j', async (terminal) => {
    const wrapper = view(incidentFixture(), { tournamentId: '20' })
    expect(wrapper.find('[data-testid="match-adjudication"]').exists()).toBe(true)
    await wrapper.setProps({ fixture: incidentFixture(terminal) })
    expect(wrapper.find('[data-testid="match-adjudication"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="match-dialog-status"]').text()).not.toBe(
      'Awaiting administrator decision',
    )
  })

  it('uses a newer cleared event instead of old incident details', async () => {
    const value = incidentFixture()
    const wrapper = view(value, { tournamentId: '20' })
    wrapper.getComponent(TournamentMatchAdminPanel).vm.$emit('loaded', administration())
    await wrapper.vm.$nextTick()
    await wrapper.setProps({
      fixture: fixture({
        live: {
          ...value.live!,
          event_revision: 3,
          event_type: 'admin_cleared',
          state: { ...value.live!.state, presence: { needsAdminAdjudication: false } },
        },
      }),
    })
    expect(wrapper.find('[data-testid="match-adjudication"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="match-dialog-status"]').text()).not.toBe(
      'Awaiting administrator decision',
    )
  })

  it('keeps all close paths locked during an organizer mutation and forwards saves', async () => {
    const wrapper = view(fixture(), { tournamentId: '20' })
    const panel = wrapper.getComponent(TournamentMatchAdminPanel)
    panel.vm.$emit('busy', true)
    await wrapper.vm.$nextTick()
    expect(
      wrapper
        .findAll('[data-section]')
        .every((button) => button.attributes('disabled') !== undefined),
    ).toBe(true)
    expect(wrapper.getComponent(Drawer).props('showCloseIcon')).toBe(false)
    expect(wrapper.getComponent(Drawer).props('closeOnEscape')).toBe(false)
    expect(wrapper.get('.match-dialog__footer button').attributes('disabled')).toBeDefined()
    wrapper.getComponent(Drawer).vm.$emit('update:visible', false)
    expect(wrapper.emitted('close')).toBeUndefined()
    panel.vm.$emit('saved')
    expect(wrapper.emitted('saved')).toHaveLength(1)
    panel.vm.$emit('busy', false)
    await wrapper.vm.$nextTick()
    await wrapper.get('.match-dialog__footer button').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
