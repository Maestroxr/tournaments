import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import PrimeVue from 'primevue/config'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TournamentWorkspaceLayout from './TournamentWorkspaceLayout.vue'
import TournamentProgress from '@/components/tournament/TournamentProgress.vue'
import TournamentReadyAlert from '@/components/tournament/TournamentReadyAlert.vue'
import StartTournamentDialog from '@/components/tournament/StartTournamentDialog.vue'
import { useTournamentWorkspace } from '@/composables/useTournamentWorkspace'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(),
  apiFetch: vi.fn(),
}))

const api = vi.mocked(apiFetch)
const root = defineComponent({ template: '<RouterView />' })
const page = (name: string) => defineComponent({
  setup() {
    const workspace = useTournamentWorkspace()
    return { refreshWorkspace: () => workspace?.refresh() }
  },
  template: `<div data-testid="workspace-page">${name}</div><button data-testid="workspace-refresh" @click="refreshWorkspace">refresh</button>`,
})

function createWorkspaceRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/tournaments/:id',
        component: TournamentWorkspaceLayout,
        children: [
          { path: 'overview', name: 'tournament-detail', component: page('overview') },
          { path: 'settings', name: 'tournament-settings', component: page('settings') },
          { path: 'players', name: 'tournament-players', component: page('players') },
          { path: 'live', name: 'tournament-live', component: page('live') },
          { path: 'bracket', name: 'tournament-bracket', component: page('bracket') },
          { path: 'standings', name: 'tournament-standings', component: page('standings') },
          { path: 'results', name: 'tournament-results', component: page('results') },
        ],
      },
    ],
  })
}

describe('TournamentWorkspaceLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.mockReset()
    useI18n().locale.value = 'en'
    api.mockResolvedValue({
      id: 20,
      name: 'Club cup',
      state: 'open',
      lifecycle_state: 'ready_to_start',
      participant_count: 6,
      min_players: 6,
      max_players: 8,
    })
  })

  it('keeps one shared title and tournament progress across every workspace route', async () => {
    const router = createWorkspaceRouter()
    await router.push('/tournaments/20/overview')
    await router.isReady()
    const wrapper = mount(root, {
      global: {
        plugins: [router, PrimeVue],
        stubs: {
          TournamentWorkspaceSidebar: true,
          TournamentStatusBadge: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.get('h1').text()).toBe('Club cup')
    expect(wrapper.findAllComponents(TournamentProgress)).toHaveLength(1)
    const sharedProgress = wrapper.getComponent(TournamentProgress)
    expect(sharedProgress.props()).toMatchObject({
      state: 'open',
      lifecycleState: 'ready_to_start',
      participantCount: 6,
      minPlayers: 6,
    })
    const sharedProgressElement = sharedProgress.element
    expect(wrapper.findComponent(TournamentReadyAlert).exists()).toBe(false)

    for (const route of ['settings', 'players', 'live', 'bracket', 'standings', 'results']) {
      await router.push(`/tournaments/20/${route}`)
      await flushPromises()

      expect(wrapper.get('[data-testid="workspace-page"]').text()).toBe(route)
      expect(wrapper.get('h1').text()).toBe('Club cup')
      expect(wrapper.findAllComponents(TournamentProgress)).toHaveLength(1)
      expect(wrapper.getComponent(TournamentProgress).element).toBe(sharedProgressElement)
      expect(wrapper.getComponent(TournamentReadyAlert).props()).toMatchObject({
        participantCount: 6,
        minPlayers: 6,
      })
    }

    expect(api).toHaveBeenCalledTimes(1)
    expect(api).toHaveBeenCalledWith('/api/admin/tournaments/20')
    wrapper.unmount()
  })

  it('starts a ready tournament from the current workspace page after confirmation', async () => {
    const openTournament = {
      id: 20,
      name: 'Club cup',
      state: 'open',
      lifecycle_state: 'ready_to_start',
      participant_count: 6,
      min_players: 6,
      max_players: 8,
    }
    api.mockResolvedValueOnce(openTournament)
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({ ...openTournament, state: 'active', lifecycle_state: 'active' })
    const router = createWorkspaceRouter()
    await router.push('/tournaments/20/players')
    await router.isReady()
    const wrapper = mount(root, {
      global: {
        plugins: [router, PrimeVue],
        stubs: {
          TournamentWorkspaceSidebar: true,
          TournamentStatusBadge: true,
        },
      },
    })
    await flushPromises()

    wrapper.getComponent(TournamentReadyAlert).vm.$emit('start')
    await flushPromises()
    expect(wrapper.getComponent(StartTournamentDialog).props()).toMatchObject({
      name: 'Club cup',
      participantCount: 6,
    })

    wrapper.getComponent(StartTournamentDialog).vm.$emit('confirm')
    await flushPromises()

    expect(api).toHaveBeenNthCalledWith(2, '/api/admin/tournaments/20/start', { method: 'POST' })
    expect(router.currentRoute.value.fullPath).toBe('/tournaments/20/players')
    expect(wrapper.findComponent(StartTournamentDialog).exists()).toBe(false)
    expect(wrapper.findComponent(TournamentReadyAlert).exists()).toBe(false)
    wrapper.unmount()
  })

  it('does not alert before the minimum player count is reached', async () => {
    api.mockResolvedValueOnce({
      id: 20,
      name: 'Club cup',
      state: 'open',
      lifecycle_state: 'registration_open',
      participant_count: 5,
      min_players: 6,
      max_players: 8,
    })
    const router = createWorkspaceRouter()
    await router.push('/tournaments/20/players')
    await router.isReady()
    const wrapper = mount(root, {
      global: {
        plugins: [router, PrimeVue],
        stubs: {
          TournamentWorkspaceSidebar: true,
          TournamentStatusBadge: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.findComponent(TournamentReadyAlert).exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows the alert immediately when a child refresh reaches the minimum', async () => {
    const waiting = {
      id: 20,
      name: 'Club cup',
      state: 'open',
      lifecycle_state: 'registration_open',
      participant_count: 5,
      min_players: 6,
      max_players: 8,
    }
    api.mockResolvedValueOnce(waiting).mockResolvedValueOnce({
      ...waiting,
      participant_count: 6,
    })
    const router = createWorkspaceRouter()
    await router.push('/tournaments/20/players')
    await router.isReady()
    const wrapper = mount(root, {
      global: {
        plugins: [router, PrimeVue],
        stubs: {
          TournamentWorkspaceSidebar: true,
          TournamentStatusBadge: true,
        },
      },
    })
    await flushPromises()
    expect(wrapper.findComponent(TournamentReadyAlert).exists()).toBe(false)

    await wrapper.get('[data-testid="workspace-refresh"]').trigger('click')
    await flushPromises()

    expect(wrapper.getComponent(TournamentReadyAlert).props('participantCount')).toBe(6)
    expect(api).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
