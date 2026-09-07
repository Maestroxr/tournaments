import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PrimeVue from 'primevue/config'
import Select from 'primevue/select'
import Checkbox from 'primevue/checkbox'
import InputNumber from 'primevue/inputnumber'
import TournamentMatchAdminPanel from './TournamentMatchAdminPanel.vue'
import TournamentBracketMatch from './TournamentBracketMatch.vue'
import { apiFetch, ApiError } from '@/services/api'
import { useI18n } from '@/i18n'
import type { MatchAdministration } from '@/types/matchAdministration'
import type { TournamentFixture } from '@/types/tournamentProgress'

vi.mock('@/services/api', async (original) => ({
  ...(await original<typeof import('@/services/api')>()),
  apiFetch: vi.fn(),
}))
const api = vi.mocked(apiFetch)
const url = '/api/admin/tournaments/20/matches/12'
function data(extra: Partial<MatchAdministration> = {}): MatchAdministration {
  return {
    fixture_id: 12,
    version: 'v1',
    note: '',
    can_rule: true,
    target_points: 5,
    players: [
      { id: 1, name: 'Dana', disqualified: false, refundable: '50.00' },
      { id: 2, name: 'Ben', disqualified: false, refundable: '50.00' },
    ],
    result: { score: [null, null], confirmed: false, winner_id: null, resolution: '' },
    times: { connection_created_at: null, live_started_at: null, ended_at: null },
    history: [],
    ...extra,
  }
}
let wrapper: ReturnType<typeof mount<typeof TournamentMatchAdminPanel>>
async function view(value = data()) {
  api.mockResolvedValue(value)
  wrapper = mount(TournamentMatchAdminPanel, {
    attachTo: document.body,
    props: { tournamentId: '20', fixtureId: 12 },
    global: { plugins: [PrimeVue] },
  })
  await flushPromises()
  return wrapper
}
async function chooseAction(action: string) {
  await wrapper.setProps({ section: 'players' })
  await wrapper.get(`[data-action="${action}"]`).trigger('click')
  wrapper.getComponent(Select).vm.$emit('update:modelValue', 1)
  await wrapper.vm.$nextTick()
  await wrapper.get('#match-admin-12-reason').setValue('Repeated misconduct')
}
async function review() {
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}
const posts = () => api.mock.calls.filter(([, options]) => options?.method === 'POST')

describe('Match organizer actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useI18n().locale.value = 'en'
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    )
  })
  afterEach(() => {
    wrapper?.unmount()
    vi.unstubAllGlobals()
  })

  it('opens without writes, hides player entry and leaves timestamps empty when unknown', async () => {
    await view()
    expect(api).toHaveBeenCalledWith(url)
    expect(posts()).toHaveLength(0)
    expect(wrapper.text()).not.toContain('Enter game')
    expect(wrapper.find('.match-times').exists()).toBe(false)
    await wrapper.setProps({ section: 'times' })
    expect(wrapper.findAll('.match-times dd').map((n) => n.text())).toEqual(['—', '—', '—'])
  })

  it.each([false, true])(
    'requires review before tournament-wide disqualification, refund=%s',
    async (refund) => {
      await view()
      await chooseAction('disqualify')
      expect(wrapper.getComponent(Checkbox).props('modelValue')).toBe(false)
      if (refund) {
        wrapper.getComponent(Checkbox).vm.$emit('update:modelValue', true)
        await wrapper.vm.$nextTick()
      }
      await review()
      expect(posts()).toHaveLength(0)
      expect(wrapper.get('.match-admin__confirmation').text()).toContain(
        'Remove Dana from this tournament',
      )
      expect(wrapper.get('.match-admin__confirmation').text()).toContain('award this match to Ben')
      expect(wrapper.get('.match-admin__confirmation').text()).toContain(
        refund ? 'Credit 50' : 'No refund will be issued',
      )
      api.mockResolvedValueOnce(data({ version: 'v2', can_rule: false }))
      await wrapper.get('[data-testid="confirm-ruling"]').trigger('click')
      await flushPromises()
      expect(posts()).toHaveLength(1)
      expect(JSON.parse(posts()[0]![1]!.body as string)).toMatchObject({
        action: 'disqualify',
        participant_id: 1,
        confirm: true,
        reason: 'Repeated misconduct',
        refund,
        version: 'v1',
      })
      expect(wrapper.emitted('saved')).toHaveLength(1)
    },
  )

  it('rejects tied scores in the UI and confirms a valid official result', async () => {
    await view()
    const inputs = wrapper.findAllComponents(InputNumber)
    inputs[0]!.vm.$emit('update:modelValue', 5)
    inputs[1]!.vm.$emit('update:modelValue', 5)
    await wrapper.get('#match-admin-12-reason').setValue('Verified with referee')
    await review()
    expect(wrapper.find('[data-testid="confirm-ruling"]').exists()).toBe(false)
    inputs[1]!.vm.$emit('update:modelValue', 2)
    await review()
    expect(wrapper.get('.match-admin__confirmation').text()).toContain('5 : 2')
    api.mockResolvedValueOnce(data({ version: 'v2', can_rule: false }))
    await wrapper.get('[data-testid="confirm-ruling"]').trigger('click')
    await flushPromises()
    expect(JSON.parse(posts()[0]![1]!.body as string)).toMatchObject({
      action: 'score',
      score1: 5,
      score2: 2,
    })
  })

  it('offers a later refund only for a disqualified player with a remaining payment', async () => {
    await view(
      data({
        can_rule: false,
        players: [
          { id: 1, name: 'Dana', disqualified: true, refundable: '35.00' },
          { id: 2, name: 'Ben', disqualified: false, refundable: '50.00' },
        ],
      }),
    )
    await wrapper.setProps({ section: 'players' })
    expect(wrapper.findAll('[data-action]').map((n) => n.attributes('data-action'))).toEqual([
      'refund',
    ])
    await chooseAction('refund')
    await review()
    expect(wrapper.get('.match-admin__confirmation').text()).toContain('Credit 35')
    expect(wrapper.getComponent(Select).props('options')).toHaveLength(1)
  })

  it('keeps notes independent of final results and records the version on save', async () => {
    await view(data({ can_rule: false }))
    await wrapper.setProps({ section: 'note' })
    expect(wrapper.find('form').exists()).toBe(false)
    await wrapper.get('#match-admin-12-note').setValue('Visible to staff only')
    api.mockResolvedValueOnce(
      data({ can_rule: false, version: 'v2', note: 'Visible to staff only' }),
    )
    await wrapper.get('.note button').trigger('click')
    await flushPromises()
    expect(JSON.parse(posts()[0]![1]!.body as string)).toMatchObject({
      action: 'note',
      note: 'Visible to staff only',
      version: 'v1',
    })
  })

  it('requires a fresh read after a conflict, preserves the note draft and never auto-retries', async () => {
    await view()
    await chooseAction('disqualify')
    await wrapper.get('#match-admin-12-note').setValue('Unsaved note')
    await review()
    api.mockRejectedValueOnce(new ApiError(409, 'Conflict', '{"detail":"Match changed"}'))
    await wrapper.get('[data-testid="confirm-ruling"]').trigger('click')
    await flushPromises()
    expect(posts()).toHaveLength(1)
    expect(wrapper.find('[data-testid="confirm-ruling"]').exists()).toBe(false)
    expect(wrapper.get('.match-admin__refresh').text()).toContain('check the history')
    api.mockResolvedValueOnce(data({ version: 'v2', can_rule: false }))
    await wrapper.get('.match-admin__refresh button').trigger('click')
    await flushPromises()
    expect((wrapper.get('#match-admin-12-note').element as HTMLTextAreaElement).value).toBe(
      'Unsaved note',
    )
    expect(posts()).toHaveLength(1)
  })

  it('marks an administrative winner in the bracket without inventing scores', () => {
    const fixture: TournamentFixture = {
      id: 12,
      player1: { id: 1, name: 'Dana', user_id: 1, username: 'dana' },
      player2: { id: 2, name: 'Ben', user_id: 2, username: 'ben' },
      score1: null,
      score2: null,
      is_confirmed: true,
      admin_resolution: 'disqualify',
      winner_id: 2,
      editable: false,
      has_confirmed: false,
      confirmations: 0,
      required_confirmations: 2,
      live: null,
    }
    const card = mount(TournamentBracketMatch, { props: { fixture } })
    expect(card.get('.is-winner').text()).toContain('Ben')
    expect(card.text()).toContain('Disqualification')
    expect(card.findAll('strong').map((n) => n.text())).toEqual(['–', '–'])
    card.unmount()
  })

  it('shows only the requested section and preserves a note when switching tools', async () => {
    await view()
    expect(wrapper.get('.match-admin__section').isVisible()).toBe(true)
    expect(wrapper.get('.note').isVisible()).toBe(false)
    expect(wrapper.find('.audit').exists()).toBe(false)
    await wrapper.setProps({ section: 'note' })
    await wrapper.get('#match-admin-12-note').setValue('Keep this draft')
    expect(wrapper.get('.note').isVisible()).toBe(true)
    expect(wrapper.get('.match-admin__section').isVisible()).toBe(false)
    await wrapper.setProps({ section: 'history' })
    expect(wrapper.get('.audit').attributes('open')).toBeDefined()
    expect(wrapper.get('.note').isVisible()).toBe(false)
    await wrapper.setProps({ section: 'times' })
    expect(wrapper.get('.match-times').isVisible()).toBe(true)
    expect(wrapper.find('.audit').exists()).toBe(false)
    await wrapper.setProps({ section: 'note' })
    expect((wrapper.get('#match-admin-12-note').element as HTMLTextAreaElement).value).toBe(
      'Keep this draft',
    )
    expect(api).toHaveBeenCalledTimes(1)
    expect(posts()).toHaveLength(0)
  })

  it('requires a fresh review after leaving and returning to a ruling form', async () => {
    await view()
    await chooseAction('disqualify')
    await review()
    expect(wrapper.find('[data-testid="confirm-ruling"]').exists()).toBe(true)
    await wrapper.setProps({ section: 'live' })
    await wrapper.setProps({ section: 'players' })
    expect(wrapper.find('[data-testid="confirm-ruling"]').exists()).toBe(false)
    expect(posts()).toHaveLength(0)
  })
})
