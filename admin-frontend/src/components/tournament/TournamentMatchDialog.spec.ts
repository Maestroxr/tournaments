import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Drawer from 'primevue/drawer'
import TournamentMatchAdminPanel from './TournamentMatchAdminPanel.vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TournamentMatchDialog from './TournamentMatchDialog.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'
import type { TournamentFixture } from '@/types/tournamentProgress'

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
          props: ['section'],
          template: '<div />',
          emits: ['busy', 'saved'],
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

  it('opens read-only with names, round and score placeholders', async () => {
    const wrapper = view()
    expect(wrapper.text()).toContain('Dana')
    expect(wrapper.text()).toContain('Ben')
    expect(wrapper.text()).toContain('Semifinals')
    expect(wrapper.text()).toContain('Waiting for the game to start.')
    expect(wrapper.findAll('.match-dialog__player strong').map((n) => n.text())).toEqual(['–', '–'])
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(api).not.toHaveBeenCalled()
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

  it.each([
    { can_play: true, playability: { can_play: true, reason: 'ready' } },
    { can_play: false, playability: { can_play: false, reason: 'user_not_in_fixture' } },
    { can_play: undefined },
    { is_confirmed: true },
    { score1: 5, score2: 2 },
    { player2: null },
  ])('never offers player entry in the admin dialog: %j', (extra) => {
    const wrapper = view(fixture(extra))
    expect(wrapper.findAll('button').map((button) => button.text())).toEqual(['Close'])
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Enter game')
    expect(wrapper.text()).not.toContain('You are assigned')
    expect(wrapper.text()).not.toContain('your account')
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
