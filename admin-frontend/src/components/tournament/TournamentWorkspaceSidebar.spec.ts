import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import { useI18n } from '@/i18n'
import TournamentWorkspaceSidebar from './TournamentWorkspaceSidebar.vue'

const page = { template: '<div />' }

async function mountSidebar(state: string, path = '/tournaments/20/overview') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/tournaments/:id/overview', name: 'tournament-detail', component: page },
      { path: '/tournaments/:id/settings', name: 'tournament-settings', component: page },
      { path: '/tournaments/:id/players', name: 'tournament-players', component: page },
      { path: '/tournaments/:id/draw', name: 'tournament-draw', component: page },
      { path: '/tournaments/:id/live', name: 'tournament-live', component: page },
      { path: '/tournaments/:id/bracket', name: 'tournament-bracket', component: page },
      { path: '/tournaments/:id/standings', name: 'tournament-standings', component: page },
      { path: '/tournaments/:id/results', name: 'tournament-results', component: page },
      { path: '/tournaments', name: 'tournaments', component: page },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(TournamentWorkspaceSidebar, {
    props: { tournamentId: '20', state, lifecycleState: state === 'open' ? 'registration_open' : state },
    global: { plugins: [router] },
  })
  return { wrapper, router }
}

describe('TournamentWorkspaceSidebar', () => {
  it('organizes setup work and locks competition views before the tournament starts', async () => {
    useI18n().locale.value = 'en'
    const { wrapper } = await mountSidebar('open')

    expect(wrapper.findAll('h2').map(heading => heading.text())).toEqual([
      'Before the tournament',
      'During the tournament',
      'After the tournament',
    ])
    expect(wrapper.get('[aria-current="page"]').text()).toBe('Overview')
    expect(wrapper.get('a[href="/tournaments/20/settings"]').text()).toBe('Settings & rules')
    expect(wrapper.get('a[href="/tournaments/20/players"]').text()).toBe('Players')
    expect(wrapper.get('a[href="/tournaments/20/draw"]').text()).toBe('Draw')
    expect(wrapper.findAll('[aria-disabled="true"]')).toHaveLength(4)
  })

  it('unlocks live competition navigation after the tournament starts', async () => {
    useI18n().locale.value = 'en'
    const { wrapper } = await mountSidebar('active', '/tournaments/20/bracket')

    expect(wrapper.get('[aria-current="page"]').text()).toBe('Bracket & matches')
    expect(wrapper.get('a[href="/tournaments/20/live"]').attributes('aria-disabled')).toBeUndefined()
    expect(wrapper.get('a[href="/tournaments/20/standings"]').attributes('aria-disabled')).toBeUndefined()
    expect(wrapper.findAll('[aria-disabled="true"]')).toHaveLength(1)
  })

  it('unlocks results once the tournament is complete', async () => {
    useI18n().locale.value = 'en'
    const { wrapper } = await mountSidebar('finished', '/tournaments/20/results')

    expect(wrapper.get('[aria-current="page"]').text()).toBe('Results')
    expect(wrapper.get('a[href="/tournaments/20/results"]').attributes('aria-disabled')).toBeUndefined()
    expect(wrapper.findAll('[aria-disabled="true"]')).toHaveLength(0)
  })
})
