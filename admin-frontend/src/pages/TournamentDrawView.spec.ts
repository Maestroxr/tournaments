import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import PrimeVue from 'primevue/config'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useI18n } from '@/i18n'
import { apiFetch } from '@/services/api'
import TournamentDrawView from './TournamentDrawView.vue'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(),
  apiFetch: vi.fn(),
}))
const api = vi.mocked(apiFetch)
const participants = [
  { id: 1, name: 'Dana', user_id: 11, username: 'dana', position: 1 },
  { id: 2, name: 'Ben', user_id: 12, username: 'ben', position: 2 },
]

function draw(lifecycle_state: string, extra: Record<string, unknown> = {}) {
  return {
    tournament_id: 20,
    lifecycle_state,
    participant_count: 2,
    min_players: 2,
    generated_at: lifecycle_state === 'registration_open' ? null : '2026-09-07T10:00:00Z',
    confirmed_at: lifecycle_state === 'ready_to_start' ? '2026-09-07T10:05:00Z' : null,
    has_draw: !['registration_open', 'registration_closed'].includes(lifecycle_state),
    participants,
    ...extra,
  }
}

async function view() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/tournaments/:id/draw', name: 'tournament-draw', component: TournamentDrawView },
      { path: '/tournaments/:id/live', name: 'tournament-live', component: { template: '<div />' } },
    ],
  })
  await router.push('/tournaments/20/draw')
  await router.isReady()
  const wrapper = mount(TournamentDrawView, { global: { plugins: [router, PrimeVue] } })
  await flushPromises()
  return { wrapper, router }
}

describe('TournamentDrawView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useI18n().locale.value = 'en'
  })

  it('keeps registration open until the minimum player count is reached', async () => {
    api.mockResolvedValue(draw('registration_open', { participant_count: 1, min_players: 2 }))
    const { wrapper } = await view()

    expect(wrapper.text()).toContain('1 more players are required')
    const closeRegistration = wrapper.findAll('button').find(button =>
      button.text().includes('Close registration'),
    )!
    expect(closeRegistration.attributes('disabled')).toBeDefined()
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('lets the organizer change and save the seed order before approval', async () => {
    api.mockResolvedValue(draw('draw_ready'))
    const { wrapper } = await view()

    await wrapper.get('button[aria-label="Move Dana down"]').trigger('click')
    const save = wrapper.findAll('button').find(button => button.text().includes('Save seed order'))!
    await save.trigger('click')
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/tournaments/20/draw', {
      method: 'POST',
      body: JSON.stringify({ participant_ids: [2, 1] }),
    })
  })

  it('approves the reviewed draw without starting the tournament', async () => {
    let lifecycle = 'draw_ready'
    api.mockImplementation(async (path, options) => {
      if (String(path).endsWith('/draw/confirm') && options?.method === 'POST') lifecycle = 'ready_to_start'
      return draw(lifecycle)
    })
    const { wrapper, router } = await view()

    const approve = wrapper.findAll('button').find(button => button.text().includes('Approve draw'))!
    await approve.trigger('click')
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/tournaments/20/draw/confirm', { method: 'POST' })
    expect(wrapper.text()).toContain('Draw approved — ready to start')
    expect(router.currentRoute.value.name).toBe('tournament-draw')
  })
})
