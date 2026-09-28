import { mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FinishedTournamentCard from './FinishedTournamentCard.vue'
import TournamentMetaItem from './TournamentMetaItem.vue'
import { useI18n } from '@/i18n'

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

type Tournament = InstanceType<typeof FinishedTournamentCard>['$props']['tournament']

function mountCard(overrides: Partial<Tournament> = {}) {
  return mount(FinishedTournamentCard, {
    props: { tournament: { ...tournament, ...overrides } },
    global: {
      stubs: {
        RouterLink: RouterLinkStub,
        TournamentStatusBadge: true,
        UserQuickView: true,
      },
    },
  })
}

function prizeText(wrapper: ReturnType<typeof mountCard>) {
  const prize = wrapper.findAllComponents(TournamentMetaItem)
    .find(item => item.props('label') === 'Prize')
  return prize?.get('dd').text()
}

describe('FinishedTournamentCard', () => {
  beforeEach(() => {
    routerPush.mockReset()
    useI18n().locale.value = 'en'
  })

  it('shows a coin prize even if stale gift text is present', () => {
    const wrapper = mountCard({ prize_type: 'coins', prize_text: 'Old gift' })

    expect(prizeText(wrapper)).toBe('100.00')
    expect(wrapper.text()).not.toContain('Old gift')
  })

  it('keeps legacy prizes without gift fields as coins', () => {
    const wrapper = mountCard()

    expect(prizeText(wrapper)).toBe('100.00')
  })

  it('shows the configured gift instead of its zero coin amount', () => {
    const wrapper = mountCard({
      prize_type: 'text',
      prize_text: '  Tournament backgammon board  ',
      prize_money: '0.00',
    })

    expect(prizeText(wrapper)).toBe('Tournament backgammon board')
  })

  it.each([undefined, '', '   '])('labels a gift with missing or blank text (%s)', (giftText) => {
    const wrapper = mountCard({ prize_type: 'text', prize_text: giftText, prize_money: '0.00' })

    expect(prizeText(wrapper)).toBe('Gift')
  })

  it('updates the prize when refreshed tournament data changes its type', async () => {
    const wrapper = mountCard()

    await wrapper.setProps({ tournament: {
      ...tournament, prize_type: 'text', prize_text: 'Gift voucher', prize_money: '0.00',
    } })
    expect(prizeText(wrapper)).toBe('Gift voucher')

    await wrapper.setProps({ tournament: { ...tournament, prize_type: 'coins', prize_money: '250.00' } })
    expect(prizeText(wrapper)).toBe('250.00')
  })

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
