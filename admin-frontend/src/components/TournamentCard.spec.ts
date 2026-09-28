import { mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TournamentCard from './TournamentCard.vue'
import { useI18n } from '@/i18n'

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

type Tournament = InstanceType<typeof TournamentCard>['$props']['tournament']

function mountCard(overrides: Partial<Tournament> = {}) {
  return mount(TournamentCard, {
    props: { tournament: { ...tournament, ...overrides } },
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
  beforeEach(() => {
    routerPush.mockReset()
    useI18n().locale.value = 'en'
  })

  it('shows a coin prize with the 6B asset instead of a dollar sign', () => {
    const wrapper = mountCard({ prize_type: 'coins', prize_text: 'Old gift' })
    const prize = wrapper.get('p.text-emerald-700')

    expect(prize.text()).toBe('100.00')
    expect(prize.get('img').attributes('src')).toContain('6b-coin.png')
    expect(prize.get('img').attributes('alt')).toBe('6B')
    expect(wrapper.text()).not.toContain('$')
    expect(wrapper.text()).not.toContain('Old gift')
  })

  it('keeps legacy prizes without gift fields as coins', () => {
    const wrapper = mountCard()
    const prize = wrapper.get('p.text-emerald-700')

    expect(prize.text()).toBe('100.00')
    expect(prize.find('img').exists()).toBe(true)
  })

  it('shows the configured gift instead of its zero coin amount', () => {
    const wrapper = mountCard({
      prize_type: 'text',
      prize_text: '  Tournament backgammon board  ',
      prize_money: '0.00',
    })
    const prize = wrapper.get('p.text-emerald-700')

    expect(prize.text()).toBe('Tournament backgammon board')
    expect(prize.find('img').exists()).toBe(false)
  })

  it.each([undefined, '', '   '])('labels a gift with missing or blank text (%s)', (prizeText) => {
    const wrapper = mountCard({ prize_type: 'text', prize_text: prizeText, prize_money: '0.00' })

    expect(wrapper.get('p.text-emerald-700').text()).toBe('Gift')
  })

  it('updates the prize when refreshed tournament data changes its type', async () => {
    const wrapper = mountCard()

    await wrapper.setProps({ tournament: {
      ...tournament, prize_type: 'text', prize_text: 'Gift voucher', prize_money: '0.00',
    } })
    expect(wrapper.get('p.text-emerald-700').text()).toBe('Gift voucher')
    expect(wrapper.get('p.text-emerald-700').find('img').exists()).toBe(false)

    await wrapper.setProps({ tournament: { ...tournament, prize_type: 'coins', prize_money: '250.00' } })
    expect(wrapper.get('p.text-emerald-700').text()).toBe('250.00')
    expect(wrapper.get('p.text-emerald-700').find('img').exists()).toBe(true)
  })

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
