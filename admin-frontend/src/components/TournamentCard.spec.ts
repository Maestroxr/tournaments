import { mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TournamentCard from './TournamentCard.vue'

const routerPush = vi.hoisted(() => vi.fn())

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

const tournament = {
  id: 19,
  name: 'Test tournament',
  state: 'draft',
  creator: 'admin',
  creator_id: null,
  participant_count: 0,
  starts_at: '2026-09-07T14:20:00Z',
  min_players: 6,
  max_players: 8,
  target_points: 5,
  time_control: 'standard',
  doubling_enabled: true,
  entry_fee: '50.00',
  prize_money: '100.00',
}

function mountCard() {
  return mount(TournamentCard, {
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

describe('TournamentCard', () => {
  beforeEach(() => routerPush.mockReset())

  it('opens the tournament when the card is clicked', async () => {
    const wrapper = mountCard()

    await wrapper.get('article').trigger('click')

    expect(routerPush).toHaveBeenCalledWith('/tournaments/19?edit=1')
  })

  it('opens the tournament from the keyboard', async () => {
    const wrapper = mountCard()

    await wrapper.get('article').trigger('keydown', { key: 'Enter' })

    expect(routerPush).toHaveBeenCalledWith('/tournaments/19?edit=1')
  })

  it('does not handle clicks on the existing action link', async () => {
    const wrapper = mountCard()

    await wrapper.getComponent(RouterLinkStub).trigger('click')

    expect(routerPush).not.toHaveBeenCalled()
  })
})
