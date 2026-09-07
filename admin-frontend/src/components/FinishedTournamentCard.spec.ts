import { mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FinishedTournamentCard from './FinishedTournamentCard.vue'

const routerPush = vi.hoisted(() => vi.fn())

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

const tournament = {
  id: 5,
  name: 'Finished tournament',
  state: 'finished',
  creator: 'admin',
  creator_id: null,
  participant_count: 8,
  starts_at: '2026-09-07T14:20:00Z',
  target_points: 5,
  time_control: 'standard',
  doubling_enabled: true,
  entry_fee: '50.00',
  prize_money: '100.00',
  champion: { id: 1, name: 'Winner', position: 0 },
  podium: [{ id: 1, name: 'Winner', position: 0 }],
}

function mountCard() {
  return mount(FinishedTournamentCard, {
    props: { tournament },
    global: {
      stubs: {
        RouterLink: RouterLinkStub,
        TournamentStatusBadge: true,
        TournamentMetaItem: true,
        UserQuickView: true,
      },
    },
  })
}

describe('FinishedTournamentCard', () => {
  beforeEach(() => routerPush.mockReset())

  it('opens the results when the card is clicked', async () => {
    const wrapper = mountCard()

    await wrapper.get('article').trigger('click')

    expect(routerPush).toHaveBeenCalledWith('/tournaments/5/progress')
  })

  it('opens the results from the keyboard', async () => {
    const wrapper = mountCard()

    await wrapper.get('article').trigger('keydown', { key: 'Enter' })

    expect(routerPush).toHaveBeenCalledWith('/tournaments/5/progress')
  })

  it('does not handle clicks on the existing results link', async () => {
    const wrapper = mountCard()

    await wrapper.getComponent(RouterLinkStub).trigger('click')

    expect(routerPush).not.toHaveBeenCalled()
  })
})
