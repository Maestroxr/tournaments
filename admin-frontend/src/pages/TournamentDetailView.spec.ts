import { shallowMount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import InputText from 'primevue/inputtext'
import TournamentDetailView from './TournamentDetailView.vue'
import AppAlert from '@/components/AppAlert.vue'
import TournamentActions from '@/components/tournament/TournamentActions.vue'
import TournamentAttentionPanel from '@/components/tournament/TournamentAttentionPanel.vue'
import TournamentOverviewMetrics from '@/components/tournament/TournamentOverviewMetrics.vue'
import StartTournamentDialog from '@/components/tournament/StartTournamentDialog.vue'
import TournamentDangerDialog from '@/components/tournament/TournamentDangerDialog.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'

const { push, replace, route } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  route: { params: { id: 20 }, query: {}, name: 'tournament-detail' },
}))
vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => ({ push, replace }),
}))
vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(), apiFetch: vi.fn(),
}))
const api = vi.mocked(apiFetch)
const tournament = {
  id: 20, name: 'Club cup', state: 'open', lifecycle_state: 'ready_to_start', participant_count: 6, min_players: 6,
  max_players: 8, target_points: 5, time_control: 'normal', doubling_enabled: true,
  entry_fee: '10.00', prize_money: '100.00', starts_at: '2099-09-07T18:00:00Z',
  creator: 'organizer', creator_id: 1, participants: [],
  definition: 'stages:\n  - id: main\n    name: Main round\n    mode: knockout\npodium:\n  - main.placements[0]',
  published: true,
}
function view() {
  return shallowMount(TournamentDetailView, { props: { id: '20' }, global: { stubs: { RouterLink: true } } })
}
async function open(wrapper: ReturnType<typeof view>) {
  await flushPromises()
  wrapper.getComponent(TournamentActions).vm.$emit('start')
  await flushPromises()
}

describe('Tournament start confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.mockReset()
    route.name = 'tournament-detail'
    route.query = {}
    useI18n().locale.value = 'en'
    api.mockResolvedValue(tournament)
  })

  it('opens the custom confirmation without starting, and cancellation makes no request', async () => {
    const wrapper = view()
    await open(wrapper)
    expect(wrapper.getComponent(StartTournamentDialog).props('name')).toBe('Club cup')
    expect(api).toHaveBeenCalledTimes(1)
    wrapper.getComponent(StartTournamentDialog).vm.$emit('cancel')
    await flushPromises()
    expect(wrapper.findComponent(StartTournamentDialog).exists()).toBe(false)
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('uses the styled confirmation dialog before returning to draft', async () => {
    const wrapper = view()
    await flushPromises()
    await wrapper.get('[data-testid="revert-to-draft"]').trigger('click')
    await flushPromises()

    expect(wrapper.getComponent(TournamentDangerDialog).props('mode')).toBe('revert')
    expect(api).toHaveBeenCalledTimes(1)
    wrapper.getComponent(TournamentDangerDialog).vm.$emit('cancel')
    await flushPromises()
    expect(wrapper.findComponent(TournamentDangerDialog).exists()).toBe(false)
  })

  it('returns to draft only after the styled dialog is confirmed', async () => {
    api.mockResolvedValueOnce(tournament).mockResolvedValueOnce({}).mockResolvedValueOnce({
      ...tournament, state: 'draft', lifecycle_state: 'draft', published: false, participant_count: 0,
    })
    const wrapper = view()
    await flushPromises()
    await wrapper.get('[data-testid="revert-to-draft"]').trigger('click')
    await flushPromises()

    wrapper.getComponent(TournamentDangerDialog).vm.$emit('confirm')
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/tournaments/20/draft', { method: 'POST' })
    expect(wrapper.findComponent(TournamentDangerDialog).exists()).toBe(false)
  })

  it('saves changed draft settings before publishing and has no separate save button', async () => {
    route.name = 'tournament-settings'
    let state = 'draft'
    let savedName = 'Club cup'
    const advancedDefinition = [
      'custom-setting: keep-me',
      'stages:',
      '  - id: preliminaries',
      '    name: Groups',
      '    mode: groups',
      '    min-group-size: 3',
      '    max-group-size: 4',
      '  - id: main',
      '    name: Final',
      '    mode: knockout',
      '    played-by:',
      '      - preliminaries.placements[0]',
      'podium:',
      '  - main.placements[0]',
    ].join('\n')
    api.mockImplementation(async (path, options) => {
      if (path === '/api/admin/tournaments/20' && options?.method === 'PUT') {
        savedName = JSON.parse(String(options.body)).name
        return {}
      }
      if (path === '/api/admin/tournaments/20/publish') {
        state = 'open'
        return {}
      }
      if (path === '/api/admin/tournaments/20') {
        return {
          ...tournament,
          name: savedName,
          state,
          published: state !== 'draft',
          definition: advancedDefinition,
        }
      }
      return {}
    })
    const wrapper = view()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Save draft')
    wrapper.getComponent(InputText).vm.$emit('update:modelValue', 'Updated cup')
    await flushPromises()
    await wrapper.get('[data-testid="publish-and-add"]').trigger('click')
    await flushPromises()

    const putIndex = api.mock.calls.findIndex(([path, options]) =>
      path === '/api/admin/tournaments/20' && options?.method === 'PUT')
    const publishIndex = api.mock.calls.findIndex(([path]) =>
      path === '/api/admin/tournaments/20/publish')
    expect(putIndex).toBeGreaterThan(0)
    expect(publishIndex).toBeGreaterThan(putIndex)
    const savedPayload = JSON.parse(String(api.mock.calls[putIndex]?.[1]?.body))
    expect(savedPayload).toMatchObject({
      name: 'Updated cup',
      entry_fee: 10,
      prize_money: 100,
    })
    expect(savedPayload.definition).toMatchObject({
      'custom-setting': 'keep-me',
      stages: [
        { id: 'preliminaries', 'min-group-size': 3, 'max-group-size': 4 },
        { id: 'main', 'played-by': ['preliminaries.placements[0]'] },
      ],
    })
    expect(push).toHaveBeenCalledWith('/tournaments/20/players')
  })

  it('publishes an unchanged draft without an unnecessary save request', async () => {
    route.name = 'tournament-settings'
    let state = 'draft'
    api.mockImplementation(async (path, options) => {
      if (path === '/api/admin/tournaments/20/publish') {
        state = 'open'
        return {}
      }
      if (path === '/api/admin/tournaments/20') {
        return { ...tournament, state, published: state !== 'draft' }
      }
      return {}
    })
    const wrapper = view()
    await flushPromises()
    await wrapper.get('[data-testid="publish-and-add"]').trigger('click')
    await flushPromises()

    expect(api).not.toHaveBeenCalledWith('/api/admin/tournaments/20', {
      method: 'PUT',
      body: expect.any(String),
    })
    expect(api).toHaveBeenCalledWith('/api/admin/tournaments/20/publish', { method: 'POST' })
    expect(push).toHaveBeenCalledWith('/tournaments/20/players')
  })

  it('does not publish when saving changed draft settings fails', async () => {
    route.name = 'tournament-settings'
    api.mockImplementation(async (path, options) => {
      if (path === '/api/admin/tournaments/20' && options?.method === 'PUT') {
        throw new Error('Draft save failed')
      }
      if (path === '/api/admin/tournaments/20') {
        return { ...tournament, state: 'draft', published: false }
      }
      return {}
    })
    const wrapper = view()
    await flushPromises()
    wrapper.getComponent(InputText).vm.$emit('update:modelValue', 'Unsaved cup')
    await flushPromises()
    await wrapper.get('[data-testid="publish-and-add"]').trigger('click')
    await flushPromises()

    expect(api).not.toHaveBeenCalledWith('/api/admin/tournaments/20/publish', expect.anything())
    expect(push).not.toHaveBeenCalled()
    expect(wrapper.getComponent(AppAlert).props('message')).toBe('Draft save failed')
  })

  it('starts only after confirmation and prevents duplicate submission', async () => {
    let resolve!: (value: unknown) => void
    api.mockResolvedValueOnce(tournament).mockImplementationOnce(() => new Promise(done => { resolve = done }))
      .mockResolvedValueOnce({ ...tournament, state: 'active', lifecycle_state: 'active' })
    const wrapper = view()
    await open(wrapper)
    const dialog = wrapper.getComponent(StartTournamentDialog)
    dialog.vm.$emit('confirm')
    await flushPromises()
    expect(dialog.props('busy')).toBe(true)
    dialog.vm.$emit('confirm')
    expect(api).toHaveBeenCalledTimes(2)
    expect(api).toHaveBeenLastCalledWith('/api/admin/tournaments/20/start', { method: 'POST' })
    resolve({})
    await flushPromises()
    expect(wrapper.findComponent(StartTournamentDialog).exists()).toBe(false)
    expect(wrapper.getComponent(TournamentActions).props('state')).toBe('active')
    expect(replace).not.toHaveBeenCalled()
  })

  it('keeps the dialog open with an error when starting fails', async () => {
    api.mockResolvedValueOnce(tournament).mockRejectedValueOnce(new Error('Unable to start'))
    const wrapper = view()
    await open(wrapper)
    wrapper.getComponent(StartTournamentDialog).vm.$emit('confirm')
    await flushPromises()
    expect(wrapper.getComponent(StartTournamentDialog).props('error')).toBe('Unable to start')
    expect(wrapper.getComponent(StartTournamentDialog).props('busy')).toBe(false)
    expect(replace).not.toHaveBeenCalled()
  })

  it('does not offer confirmation when there are not enough players', async () => {
    api.mockResolvedValueOnce({ ...tournament, lifecycle_state: 'registration_open', participant_count: 5 })
    const wrapper = view()
    await open(wrapper)
    expect(wrapper.findComponent(StartTournamentDialog).exists()).toBe(false)
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('builds the organizer snapshot and actionable player blocker from tournament data', async () => {
    api.mockResolvedValueOnce({ ...tournament, lifecycle_state: 'registration_open', participant_count: 4 })
    const wrapper = view()
    await flushPromises()

    const metrics = wrapper.getComponent(TournamentOverviewMetrics).props('metrics')
    expect(metrics.find((metric: { id: string }) => metric.id === 'registration')!.value).toBe('4/8')
    expect(metrics.find((metric: { id: string }) => metric.id === 'readiness')!.value).toBe('4/5')
    const attention = wrapper.getComponent(TournamentAttentionPanel).props('items')
    expect(attention.map((item: { id: string }) => item.id)).toEqual(['players'])
    expect(attention[0]!.to).toBe('/tournaments/20/players')
  })

  it('keeps payment and waitlist attention actionable without mentioning check-in', async () => {
    api.mockResolvedValueOnce({
      ...tournament,
      lifecycle_state: 'registration_open',
      registration_summary: {
        registered: 6, checked_in: 4, unpaid: 1, waitlisted: 2, attention: 4, ready: 3,
      },
    })
    const wrapper = view()
    await flushPromises()

    const metrics = wrapper.getComponent(TournamentOverviewMetrics).props('metrics')
    expect(metrics.map((metric: { id: string }) => metric.id)).not.toContain('participant-readiness')
    const attention = wrapper.getComponent(TournamentAttentionPanel).props('items')
    expect(attention.map((item: { id: string }) => item.id)).toContain('participant-readiness')
    const participantAttention = attention.find((item: { id: string }) => item.id === 'participant-readiness')!
    expect(participantAttention.title).toBe('3 participants require attention')
    expect(participantAttention.detail).toBe('Unpaid: 1 · Waitlist: 2')
    expect(participantAttention.detail).not.toContain('check')
    expect(participantAttention.to).toBe('/tournaments/20/players')
  })

  it('ignores legacy missing check-ins and still offers the start confirmation', async () => {
    api.mockResolvedValueOnce({
      ...tournament,
      registration_summary: {
        registered: 6, checked_in: 0, unpaid: 0, waitlisted: 0, attention: 6, ready: 0,
      },
    })
    const wrapper = view()
    await flushPromises()

    const attention = wrapper.getComponent(TournamentAttentionPanel).props('items')
    expect(attention.map((item: { id: string }) => item.id)).not.toContain('participant-readiness')

    wrapper.getComponent(TournamentActions).vm.$emit('start')
    await flushPromises()
    expect(wrapper.getComponent(StartTournamentDialog).props('name')).toBe('Club cup')
  })

  it('loads match health for an active tournament and separates pending confirmations', async () => {
    api.mockResolvedValueOnce({ ...tournament, state: 'active', lifecycle_state: 'active' }).mockResolvedValueOnce({
      tournament: { id: 20, name: 'Club cup', state: 'active', participant_count: 6 },
      stages: {
        main: {
          levels: [{ fixtures: [
            { id: 1, player1: { id: 1 }, player2: { id: 2 }, is_confirmed: true, confirmations: 2 },
            { id: 2, player1: { id: 3 }, player2: { id: 4 }, is_confirmed: false, confirmations: 1 },
            { id: 3, player1: { id: 5 }, player2: { id: 6 }, is_confirmed: false, confirmations: 0 },
          ] }],
        },
      },
      is_finished: false,
      podium: [],
    })
    const wrapper = view()
    await flushPromises()

    expect(api).toHaveBeenNthCalledWith(2, '/api/admin/tournaments/20/progress')
    const metrics = wrapper.getComponent(TournamentOverviewMetrics).props('metrics')
    expect(metrics.find((metric: { id: string }) => metric.id === 'matches')!.value).toBe('1/3')
    const attention = wrapper.getComponent(TournamentAttentionPanel).props('items')
    expect(attention.map((item: { id: string }) => item.id)).toEqual([
      'confirmation',
      'pending-matches',
    ])
  })

  it.each(['active', 'finished'])('keeps an existing %s tournament overview available', async state => {
    api.mockResolvedValueOnce({ ...tournament, state, lifecycle_state: state })
    const wrapper = view()
    await flushPromises()
    expect(wrapper.text()).toContain('Overview')
    expect(replace).not.toHaveBeenCalled()
  })
})
