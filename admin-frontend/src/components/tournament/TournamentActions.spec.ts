import { mount, RouterLinkStub } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TournamentActions from './TournamentActions.vue'
import TournamentActionCard from './TournamentActionCard.vue'

function mountActions(
  participantCount = 0,
  state = 'open',
  starting = false,
  hasFormat = true,
  lifecycleState = state === 'open' && participantCount >= 6 ? 'ready_to_start' : state === 'open' ? 'registration_open' : state,
) {
  return mount(TournamentActions, {
    props: { tournamentId: 20, state, lifecycleState, participantCount, minPlayers: 6, starting, hasFormat },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

describe('TournamentActions', () => {
  it('makes player management the primary action before minimum registration', async () => {
    const wrapper = mountActions(5)
    expect(wrapper.text()).toContain('1 more players needed to start')
    const primary = wrapper.findAllComponents(TournamentActionCard)[0]!
    expect(primary.props('to')).toBe('/tournaments/20/players')
    expect(primary.props('tone')).toBe('green')
    primary.vm.$emit('activate')
    expect(wrapper.emitted('start')).toBeUndefined()
    const links = wrapper.findAllComponents(RouterLinkStub)
    expect(links.map(link => link.props('to'))).toEqual([
      '/tournaments/20/players',
      '/tournaments/20/settings',
    ])
  })

  it('allows starting at the minimum, and blocks duplicate clicks while starting', async () => {
    const wrapper = mountActions(6)
    wrapper.findAllComponents(TournamentActionCard)[0]!.vm.$emit('activate')
    expect(wrapper.emitted('start')).toHaveLength(1)
    await wrapper.setProps({ starting: true })
    expect(wrapper.findAllComponents(TournamentActionCard)[0]!.props('loading')).toBe(true)
    wrapper.findAllComponents(TournamentActionCard)[0]!.vm.$emit('activate')
    expect(wrapper.emitted('start')).toHaveLength(1)
  })

  it('starts directly when an open registration has enough players', () => {
    const wrapper = mountActions(6, 'open', false, true, 'registration_open')
    const primary = wrapper.findAllComponents(TournamentActionCard)[0]!
    expect(primary.props('to')).toBeUndefined()
    expect(wrapper.text()).toContain('Start tournament')
    primary.vm.$emit('activate')
    expect(wrapper.emitted('start')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('draw workspace')
  })

  it('makes live control primary for an active tournament and keeps related shortcuts', () => {
    const wrapper = mountActions(6, 'active')
    expect(wrapper.text()).not.toContain('Start tournament')
    expect(wrapper.findAllComponents(RouterLinkStub).map(link => link.props('to')))
      .toEqual([
        '/tournaments/20/live',
        '/tournaments/20/settings',
        '/tournaments/20/players',
        '/tournaments/20/bracket',
        '/tournaments/20/standings',
      ])
  })

  it('publishes a valid draft and sends an incomplete draft to settings', async () => {
    const readyDraft = mountActions(0, 'draft')
    readyDraft.findAllComponents(TournamentActionCard)[0]!.vm.$emit('activate')
    expect(readyDraft.emitted('publish')).toHaveLength(1)

    const incompleteDraft = mountActions(0, 'draft', false, false)
    expect(incompleteDraft.findAllComponents(TournamentActionCard)[0]!.props('to'))
      .toBe('/tournaments/20/settings')
    incompleteDraft.findAllComponents(TournamentActionCard)[0]!.vm.$emit('activate')
    expect(incompleteDraft.emitted('publish')).toBeUndefined()
  })

  it('makes final results primary once the tournament is finished', () => {
    const wrapper = mountActions(6, 'finished')
    expect(wrapper.findAllComponents(TournamentActionCard)[0]!.props('to'))
      .toBe('/tournaments/20/results')
  })
})
