import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PrimeVue from 'primevue/config'
import SelectButton from 'primevue/selectbutton'
import DashboardView from './DashboardView.vue'
import TournamentStatusBadge from '@/components/TournamentStatusBadge.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(), apiFetch: vi.fn(),
}))

const api = vi.mocked(apiFetch)
const response = {
  updated_at: '2026-09-07T12:00:00Z',
  range_days: 7,
  kpis: {
    active: { value: 1, context: 'legacy server text', attention_count: 1 },
    upcoming: { value: 2, context: 'legacy server text', days: 7 },
    waiting: { value: 1, context: 'legacy server text', missing_players: 3 },
    pending_matches: { value: 2, context: 'legacy server text' },
    new_users: { value: 4, context: 'legacy server text', delta: 2 },
  },
  counts: { draft: 1, open: 1, active: 1, finished: 0 },
  attention: [{
    id: 3,
    name: 'אליפות ירושלים',
    state: 'active',
    starts_at: '2026-09-07T10:00:00Z',
    participant_count: 8,
    min_players: 4,
    max_players: 16,
    pending_matches: 2,
    kind: 'pending_matches',
    severity: 'warning',
    message: 'legacy server text',
    action_label: 'legacy server text',
    action_to: '/tournaments/3/live',
  }],
  active_tournaments: [{
    id: 3,
    name: 'אליפות ירושלים',
    state: 'active',
    starts_at: '2026-09-07T10:00:00Z',
    participant_count: 8,
    min_players: 4,
    max_players: 16,
    stage: 'Quarter-finals',
    round: 'Round 2',
    pending_matches: 2,
    round_completed_matches: 2,
    round_total_matches: 4,
    round_progress_percent: 50,
    next_match: { id: 44, player1: 'Dana', player2: 'Noam' },
  }],
  upcoming_tournaments: [{
    id: 4,
    name: 'Open Tel Aviv',
    state: 'open',
    starts_at: '2026-09-09T17:30:00Z',
    participant_count: 5,
    min_players: 8,
    max_players: 16,
    entry_fee: '50.00',
    registration_summary: {
      registered: 5,
      checked_in: 2,
      unpaid: 1,
      waitlisted: 1,
      attention: 4,
      ready: 1,
    },
  }],
  recent_activity: [{
    id: 'wallet-8',
    kind: 'wallet',
    action: 'tournament_entry',
    actor: 'organizer',
    subject: 'dana',
    amount: '-50.00',
    tournament_name: 'Open Tel Aviv',
    created_at: '2026-09-07T11:30:00Z',
    to: '/tournaments/4/overview',
  }],
  finance: {
    revenue: '900.00',
    refunds: '50.00',
    prizes: '300.00',
    expenses: '350.00',
    net: '550.00',
    outstanding: '100.00',
    outstanding_count: 2,
  },
}

function view() {
  return mount(DashboardView, {
    global: {
      plugins: [PrimeVue],
      stubs: {
        RouterLink: { props: ['to'], template: '<a :data-to="to"><slot /></a>' },
      },
    },
  })
}

describe('DashboardView localization', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useI18n().locale.value = 'en'
    api.mockResolvedValue(response)
  })

  it('renders English dashboard labels from the translation catalog', async () => {
    const wrapper = view()
    await flushPromises()

    expect(wrapper.text()).toContain('Tournament operations at a glance')
    expect(wrapper.text()).toContain('2 matches waiting for results')
    expect(wrapper.text()).toContain('A result is required now')
    expect(wrapper.text()).toContain('In progress')
    expect(wrapper.text()).toContain('Continue managing אליפות ירושלים')
    expect(wrapper.get('.dashboard-focus-card').text()).toContain('Next: Dana vs. Noam')
    expect(wrapper.get('.dashboard-focus-card').text()).toContain('2/4')
    expect(wrapper.text()).toContain('Open control room')
    expect(wrapper.text()).not.toContain('Create user')
    const kpis = wrapper.findAll('.admin-kpi')
    expect(kpis).toHaveLength(4)
    expect(kpis[0]?.text()).toContain('Pending matches')
    expect(kpis[0]?.classes()).toContain('admin-kpi--critical')
    expect(kpis[1]?.classes()).toContain('admin-kpi--warning')
    expect(wrapper.text()).toContain('Today and upcoming')
    expect(wrapper.text()).toContain('Registration progress')
    expect(wrapper.text()).toContain('Unpaid: 1')
    expect(wrapper.text()).not.toContain('Checked in')
    expect(wrapper.get('[aria-label="Registration progress for Open Tel Aviv"]').attributes('aria-valuenow')).toBe('63')
    expect(wrapper.text()).not.toContain('Recently added users')
    expect(wrapper.text()).not.toContain('New users')
    expect(wrapper.text()).toContain('Recent activity')
    expect(wrapper.text()).toContain('organizer charged an entry fee of $50.00 for dana')
    expect(wrapper.text()).toContain('Financial snapshot')
    expect(wrapper.text()).toContain('$550.00')
    expect(wrapper.findAll('a').some(link => link.attributes('data-to') === '/transfers/finance')).toBe(true)
    expect(wrapper.findAll('.admin-attention a').some(link => link.attributes('data-to') === '/tournaments/3/live')).toBe(true)
    expect(wrapper.findAll('.dashboard-upcoming-grid a').some(link => link.attributes('data-to') === '/tournaments/4/players')).toBe(true)
    expect(wrapper.findAll('.admin-tournament-card')).toHaveLength(0)
    const html = wrapper.html()
    expect(html.indexOf('attention-heading')).toBeLessThan(html.indexOf('upcoming-heading'))
    expect(html.indexOf('upcoming-heading')).toBeLessThan(html.indexOf('kpi-heading'))
    expect(wrapper.text()).not.toContain('legacy server text')
    expect(document.documentElement.dir).toBe('ltr')
  })

  it('does not crash when an older backend omits the recent activity feed', async () => {
    const { recent_activity: _recentActivity, ...legacyResponse } = response
    api.mockResolvedValue({
      ...legacyResponse,
      active_tournaments: legacyResponse.active_tournaments.map((tournament) => {
        const {
          round_completed_matches: _roundCompleted,
          round_total_matches: _roundTotal,
          round_progress_percent: _roundPercent,
          next_match: _nextMatch,
          ...legacyTournament
        } = tournament
        return legacyTournament
      }),
      recent_users: [{ id: 1, username: 'legacy-user' }],
    } as never)

    const wrapper = view()
    await flushPromises()

    expect(wrapper.text()).toContain('Tournament operations at a glance')
    expect(wrapper.text()).toContain('No operational activity has been recorded yet.')
    expect(wrapper.get('.dashboard-focus-card').text()).toContain('0/2')
  })

  it('uses safe empty collections when a rolling deployment returns a partial payload', async () => {
    api.mockResolvedValue({
      updated_at: '2026-09-07T12:00:00Z',
      range_days: 7,
      kpis: response.kpis,
      counts: response.counts,
    } as never)

    const wrapper = view()
    await flushPromises()

    expect(wrapper.text()).toContain('Create a tournament')
    expect(wrapper.text()).toContain('Everything is on track')
    expect(wrapper.text()).toContain('No operational activity has been recorded yet.')
  })

  it('renders the complete dashboard interface in Hebrew and RTL', async () => {
    useI18n().locale.value = 'he'
    const wrapper = view()
    await flushPromises()

    expect(wrapper.text()).toContain('תפעול טורנירים במבט מהיר')
    expect(wrapper.text()).toContain('2 משחקים ממתינים לתוצאה')
    expect(wrapper.text()).toContain('מתנהל כעת')
    expect(wrapper.text()).toContain('פתיחת חדר הבקרה')
    expect(wrapper.text()).toContain('היום ובקרוב')
    expect(wrapper.text()).toContain('התקדמות ההרשמה')
    expect(wrapper.text()).toContain('5/8')
    expect(wrapper.text()).toContain('פעילות אחרונה')
    expect(wrapper.text()).toContain('organizer גבה דמי כניסה בסך')
    expect(wrapper.text()).toContain('עבור dana')
    expect(wrapper.findAllComponents(TournamentStatusBadge)[0]?.props('label')).toBe('מתנהל כעת')
    expect(wrapper.text()).not.toContain('legacy server text')
    expect(document.documentElement.lang).toBe('he')
    expect(document.documentElement.dir).toBe('rtl')
  })

  it('falls back to the nearest upcoming tournament when none is active', async () => {
    api.mockResolvedValue({
      ...response,
      active_tournaments: [],
      kpis: { ...response.kpis, active: { ...response.kpis.active, value: 0 } },
      counts: { ...response.counts, active: 0 },
    })
    const wrapper = view()
    await flushPromises()

    const focus = wrapper.get('.dashboard-focus-card').text()
    expect(focus).toContain('Open Tel Aviv')
    expect(focus).toContain('Manage players')
    expect(focus).not.toContain('Open control room')
    expect(focus).not.toContain('Create tournament')
    expect(focus).toContain('Unpaid')
    expect(focus).toContain('1')
    expect(focus).not.toContain('Checked in')
    expect(wrapper.find('.dashboard-upcoming-grid').exists()).toBe(false)
    expect(wrapper.text()).toContain('The next tournament is shown in the action area above.')
  })

  it('alerts the admin and offers the start flow when registration reaches the minimum', async () => {
    const baseTournament = response.upcoming_tournaments[0]!
    const readyTournament = {
      ...baseTournament,
      participant_count: 8,
      registration_summary: {
        ...baseTournament.registration_summary,
        registered: 8,
      },
    }
    api.mockResolvedValue({
      ...response,
      active_tournaments: [],
      upcoming_tournaments: [readyTournament],
      attention: [{
        ...readyTournament,
        kind: 'ready_to_start',
        severity: 'info',
        message: 'server fallback',
        action_label: 'server fallback',
        action_to: '/tournaments/4/overview',
      }],
    })
    const wrapper = view()
    await flushPromises()

    const focus = wrapper.get('.dashboard-focus-card')
    expect(focus.text()).toContain('Start tournament')
    expect(focus.findAll('a').some(link => link.attributes('data-to') === '/tournaments/4/overview')).toBe(true)
    expect(wrapper.get('.admin-attention').text()).toContain('Ready to start')
    expect(wrapper.get('.admin-attention').text()).toContain('8 players are registered')
    expect(wrapper.get('.admin-attention').text()).toContain('The tournament can be started now')
    expect(wrapper.get('.admin-attention a[data-to="/tournaments/4/overview"]').text()).toContain('Start tournament')

    const registrationFilter = wrapper.findAll('button').find(button => button.text().includes('Registration'))
    await registrationFilter?.trigger('click')
    expect(wrapper.findAll('.admin-attention > div')).toHaveLength(1)
    expect(wrapper.get('.admin-attention').text()).toContain('Ready to start')
  })

  it('falls back to a draft when there is no active or upcoming tournament', async () => {
    const draft = {
      ...response.attention[0],
      id: 9,
      name: 'Draft Cup',
      state: 'draft',
      kind: 'draft',
      action_to: '/tournaments/9/overview?edit=1',
    }
    api.mockResolvedValue({
      ...response,
      active_tournaments: [],
      upcoming_tournaments: [],
      attention: [draft],
    })
    const wrapper = view()
    await flushPromises()

    const focus = wrapper.get('.dashboard-focus-card').text()
    expect(focus).toContain('Draft Cup')
    expect(focus).toContain('Continue editing')
    expect(focus).not.toContain('Create tournament')
  })

  it('offers tournament creation only when no tournament needs focus', async () => {
    api.mockResolvedValue({
      ...response,
      active_tournaments: [],
      upcoming_tournaments: [],
      attention: [],
      counts: { draft: 0, open: 0, active: 0, finished: 0 },
    })
    const wrapper = view()
    await flushPromises()

    const focus = wrapper.get('.dashboard-focus-card').text()
    expect(focus).toContain('Create a tournament')
    expect(focus).toContain('Create tournament')
    expect(focus).not.toContain('Open control room')
  })

  it('keeps operational KPI cards neutral when no action is required', async () => {
    api.mockResolvedValue({
      ...response,
      kpis: {
        ...response.kpis,
        active: { ...response.kpis.active, attention_count: 0 },
        waiting: { ...response.kpis.waiting, value: 0, missing_players: 0 },
        pending_matches: { ...response.kpis.pending_matches, value: 0 },
      },
    })
    const wrapper = view()
    await flushPromises()

    expect(wrapper.findAll('.admin-kpi')).toHaveLength(4)
    expect(wrapper.findAll('.admin-kpi--neutral')).toHaveLength(4)
    expect(wrapper.find('.admin-kpi--critical').exists()).toBe(false)
    expect(wrapper.find('.admin-kpi--warning').exists()).toBe(false)
  })

  it('reloads the dashboard when the upcoming range changes', async () => {
    const wrapper = view()
    await flushPromises()

    wrapper.getComponent(SelectButton).vm.$emit('update:modelValue', 30)
    await flushPromises()

    expect(api).toHaveBeenLastCalledWith('/api/admin/dashboard?days=30')
  })

  it('sorts attention by severity and filters the work queue', async () => {
    api.mockResolvedValue({
      ...response,
      attention: [
        { ...response.attention[0], id: 30, name: 'Draft Cup', kind: 'draft', severity: 'info', starts_at: null },
        { ...response.attention[0], id: 31, name: 'Registration Cup', kind: 'waiting_players', severity: 'warning', state: 'open', starts_at: '2026-09-08T10:00:00Z' },
        { ...response.attention[0], id: 32, name: 'Overdue Cup', kind: 'overdue', severity: 'critical', state: 'open', starts_at: '2026-09-06T10:00:00Z' },
        response.attention[0],
      ],
    })
    const wrapper = view()
    await flushPromises()

    const rows = wrapper.findAll('.admin-attention > div')
    expect(rows[0]?.text()).toContain('Overdue Cup')
    expect(rows.at(-1)?.text()).toContain('Draft Cup')

    const registrationFilter = wrapper.findAll('button').find(button => button.text().includes('Registration'))
    await registrationFilter?.trigger('click')

    const filteredRows = wrapper.findAll('.admin-attention > div')
    expect(filteredRows).toHaveLength(1)
    expect(filteredRows[0]?.text()).toContain('Registration Cup')
  })

  it('lists only active tournaments that are not already featured', async () => {
    api.mockResolvedValue({
      ...response,
      active_tournaments: [
        response.active_tournaments[0],
        { ...response.active_tournaments[0], id: 12, name: 'Haifa Masters' },
      ],
    })
    const wrapper = view()
    await flushPromises()

    expect(wrapper.get('.dashboard-focus-card').text()).toContain('אליפות ירושלים')
    const cards = wrapper.findAll('.admin-tournament-card')
    expect(cards).toHaveLength(1)
    expect(cards[0]?.text()).toContain('Haifa Masters')
    expect(cards[0]?.text()).not.toContain('אליפות ירושלים')
    expect(cards[0]?.text()).toContain('Next: Dana vs. Noam')
    expect(cards[0]?.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('50')
    expect(cards[0]?.findAll('a').some(link => link.attributes('data-to') === '/tournaments/12/live')).toBe(true)
  })
})
