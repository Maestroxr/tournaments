import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import PrimeVue from 'primevue/config'
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import DirectPlayView from './DirectPlayView.vue'
import GameFormatsEditor from '@/components/GameFormatsEditor.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(),
  apiFetch: vi.fn(),
}))

const api = vi.mocked(apiFetch)
enableAutoUnmount(afterEach)
const settings = {
  game_rules: Object.fromEntries(['match', 'friend', 'quick'].map(mode => [mode, {
    enabled: true, target_points: [1, 3, 5, 7, 9], time_controls: ['none', 'normal', 'fast', 'slow'], doubling_options: [true, false],
  }])),
  stake_amounts: [100, 500],
  enabled: true,
  friend_game_fee: '50.00',
  head_to_head_fee_percent: '5.00',
  tournament_fee_percent: '10.00',
  coin_grant_enabled: true,
  coin_grant_amount: '400.00',
  coin_grant_interval_hours: 12,
}
const openTable = {
  id: 7,
  code: 'FRIEND',
  mode: 'friend',
  host: 'dana',
  guest: 'noam',
  winner: null,
  amount: '200.00',
  fee_percent: '0.00',
  fee_per_player: '200.00',
  target_points: 5,
  doubling_enabled: false,
  status: 'waiting',
  external_room_id: 'room-7',
  created_at: '2026-09-10T10:00:00Z',
}

const DialogStub = defineComponent({
  props: ['visible', 'header'],
  template: '<div v-if="visible" role="dialog"><h2>{{ header }}</h2><slot /><slot name="footer" /></div>',
})

function view() {
  return mount(DirectPlayView, {
    global: { plugins: [PrimeVue], stubs: { Dialog: DialogStub, RouterLink: true } },
  })
}

describe('DirectPlayView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    useI18n().locale.value = 'en'
    api.mockImplementation(async path => {
      if (path === '/api/admin/direct-play/settings') return { ...settings }
      if (path === '/api/admin/direct-play/tables') return { tables: [{ ...openTable }] }
      return null
    })
  })

  it('switches sidebar sections while preserving unsaved settings', async () => {
    const wrapper = view()
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('Games')
    expect(wrapper.get('#games-monitor').isVisible()).toBe(true)
    expect(wrapper.get('#games-settings').isVisible()).toBe(false)
    const sidebar = wrapper.get('nav[aria-label="Game management"]')
    await sidebar.get('[aria-controls="games-friend"]').trigger('click')
    expect(wrapper.get('#games-friend').isVisible()).toBe(true)
    expect(wrapper.get('[data-game-mode="friend"]').isVisible()).toBe(true)
    expect(wrapper.get('[data-game-mode="match"]').isVisible()).toBe(false)
    expect(wrapper.get('.stake-settings').isVisible()).toBe(false)
    wrapper.findAllComponents(InputNumber)[0]!.vm.$emit('update:modelValue', 321)
    await sidebar.get('[aria-controls="games-monitor"]').trigger('click')
    expect(wrapper.get('#games-monitor').isVisible()).toBe(true)
    await sidebar.get('[aria-controls="games-friend"]').trigger('click')
    expect(wrapper.findAllComponents(InputNumber)[0]!.props('modelValue')).toBe(321)
    expect(sidebar.get('[aria-controls="games-friend"]').attributes('aria-current')).toBe('page')
    await sidebar.get('[aria-controls="games-quick"]').trigger('click')
    expect(wrapper.get('[data-game-mode="quick"]').isVisible()).toBe(true)
    expect(wrapper.get('[data-game-mode="friend"]').isVisible()).toBe(false)
    await sidebar.get('[aria-controls="games-settings"]').trigger('click')
    expect(wrapper.get('.stake-settings').isVisible()).toBe(true)
    expect(wrapper.get('[data-game-mode="quick"]').isVisible()).toBe(false)
  })

  it('saves independent format profiles with access rules and loss limits', async () => {
    const profile = { enabled: true, public: true, private: true, quick: true,
      target_points: [1], time_controls: ['normal'], doubling_options: [true],
      stake_amounts: [100], fee_percent: 5, max_cube: 8, loss_limit_multiplier: 8, jacoby: false }
    const profiles = { match: structuredClone(profile), money: { ...structuredClone(profile), jacoby: true } }
    api.mockImplementation(async path => path === '/api/admin/direct-play/settings'
      ? { ...settings, format_profiles: profiles } : { tables: [] })
    const wrapper = view()
    await flushPromises()
    await wrapper.get('[aria-controls="games-formats"]').trigger('click')
    expect(wrapper.get('#games-formats').isVisible()).toBe(true)
    const editor = wrapper.getComponent(GameFormatsEditor)
    editor.vm.$emit('update:modelValue', { ...profiles, money: { ...profiles.money, max_cube: 4, private: false } })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const request = api.mock.calls.find(([, options]) => options?.method === 'PUT')
    expect(JSON.parse(request![1]!.body as string).format_profiles.money).toMatchObject({ max_cube: 4, private: false, loss_limit_multiplier: 8 })
    expect(JSON.parse(request![1]!.body as string).format_profiles.match.max_cube).toBe(8)
  })

  it('loads the editable fees and current game tables', async () => {
    const wrapper = view()
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/direct-play/settings')
    expect(api).toHaveBeenCalledWith('/api/admin/direct-play/tables')
    expect(wrapper.text()).toContain('Fixed friend game fee')
    expect(wrapper.text()).toContain('Each player pays this fixed fee for any match length.')
    expect(wrapper.text()).toContain('Public Match Play fee')
    expect(wrapper.text()).toContain('dana')
    expect(wrapper.text()).toContain('FRIEND')
    expect(wrapper.text()).toContain('no doubling')
  })

  it('adds and removes available stakes in the saved settings', async () => {
    const wrapper = view()
    await flushPromises()
    await wrapper.get('button[aria-label="Remove amount 100"]').trigger('click')
    wrapper.findAllComponents(InputNumber)[2]!.vm.$emit('update:modelValue', 750)
    await flushPromises()
    await wrapper.get('button[aria-label="Add amount"]').trigger('click')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    const save = api.mock.calls.find(([, options]) => options?.method === 'PUT')
    expect(JSON.parse(String(save?.[1]?.body)).stake_amounts).toEqual([500, 750])
  })

  it('saves independent mode rules and refuses an empty choice group', async () => {
    const wrapper = view()
    await flushPromises()
    const quick = wrapper.get('[data-game-mode="quick"]')
    quick.getComponent(ToggleSwitch).vm.$emit('update:modelValue', false)
    quick.findAllComponents(SelectButton)[0]!.vm.$emit('update:modelValue', [1, 3, 7, 9])
    quick.findAllComponents(SelectButton)[1]!.vm.$emit('update:modelValue', ['none', 'normal', 'fast'])
    quick.findAllComponents(SelectButton)[2]!.vm.$emit('update:modelValue', [false])
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    const save = api.mock.calls.find(([, options]) => options?.method === 'PUT')
    const payload = JSON.parse(String(save?.[1]?.body))
    expect(payload.game_rules.quick).toEqual({enabled: false, target_points: [1, 3, 7, 9], time_controls: ['none', 'normal', 'fast'], doubling_options: [false]})
    expect(payload.game_rules.match).toEqual(settings.game_rules.match)
    api.mockClear()
    const friend = wrapper.get('[data-game-mode="friend"]')
    friend.findAllComponents(SelectButton)[0]!.vm.$emit('update:modelValue', [])
    await wrapper.get('form').trigger('submit.prevent')
    expect(api).not.toHaveBeenCalled()
  })

  it('saves all admin-controlled values', async () => {
    api.mockImplementation(async (path, options) => {
      if (path === '/api/admin/direct-play/settings' && options?.method === 'PUT') {
        return JSON.parse(String(options.body))
      }
      if (path === '/api/admin/direct-play/settings') return { ...settings }
      if (path === '/api/admin/direct-play/tables') return { tables: [] }
      return null
    })
    const wrapper = view()
    await flushPromises()

    const inputs = wrapper.findAllComponents(InputNumber)
    inputs[0]!.vm.$emit('update:modelValue', 250)
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/direct-play/settings', {
      method: 'PUT',
      body: JSON.stringify({
        enabled: true,
        game_rules: settings.game_rules,
        stake_amounts: [100, 500],
        friend_game_fee: 250,
        head_to_head_fee_percent: 5,
        tournament_fee_percent: 10,
        coin_grant_enabled: true,
        coin_grant_amount: 400,
        coin_grant_interval_hours: 12,
      }),
    })
    expect(wrapper.text()).toContain('Head-to-head settings were saved.')
  })

  it('separates waiting players, paired games and history and filters quick matches', async () => {
    api.mockImplementation(async path => {
      if (path === '/api/admin/direct-play/settings') return { ...settings }
      return { tables: [
        { ...openTable, guest: null, status: 'open' },
        { ...openTable, id: 8, code: 'QUICK', mode: 'match', is_quick_match: true, status: 'ready' },
        { ...openTable, id: 9, code: 'PUBLIC', mode: 'match', status: 'playing' },
        { ...openTable, id: 10, code: 'DONE', status: 'completed', winner: 'dana' },
      ] }
    })
    const wrapper = view()
    await flushPromises()
    expect(wrapper.findAll('[data-table-id]').map(row => row.attributes('data-table-id'))).toEqual(['7'])
    expect(wrapper.text()).toContain('Waiting for an opponent')
    await wrapper.get('button[aria-label="Paired / in progress (2)"]').trigger('click')
    wrapper.findAllComponents(Select).find(component => component.props('options')?.some((option: { value: string }) => option.value === 'quick'))!.vm.$emit('update:modelValue', 'quick')
    await flushPromises()
    expect(wrapper.findAll('[data-table-id]').map(row => row.attributes('data-table-id'))).toEqual(['8'])
    await wrapper.get('input[placeholder="Search player or table code"]').setValue('missing')
    expect(wrapper.findAll('[data-table-id]')).toHaveLength(0)
  })

  it('refreshes games without replacing unsaved settings', async () => {
    const wrapper = view()
    await flushPromises()
    wrapper.findAllComponents(InputNumber)[0]!.vm.$emit('update:modelValue', 321)
    api.mockClear()
    const buttons = wrapper.findAll('button[aria-label="Refresh"]')
    await buttons[1]!.trigger('click')
    await flushPromises()
    expect(api).toHaveBeenCalledWith('/api/admin/direct-play/tables')
    expect(api).not.toHaveBeenCalledWith('/api/admin/direct-play/settings')
    expect(wrapper.findAllComponents(InputNumber)[0]!.props('modelValue')).toBe(321)
  })

  it('limits the tournament fee to the configured 8–10 percent range', async () => {
    const wrapper = view()
    await flushPromises()

    const inputs = wrapper.findAllComponents(InputNumber)
    expect(inputs[3]!.props('min')).toBe(8)
    expect(inputs[3]!.props('max')).toBe(10)
    inputs[3]!.vm.$emit('update:modelValue', 7)
    await wrapper.get('form').trigger('submit.prevent')

    expect(api).not.toHaveBeenCalledWith('/api/admin/direct-play/settings', expect.objectContaining({ method: 'PUT' }))
    expect(wrapper.text()).toContain('tournament fee must be between 8% and 10%')
  })

  it('requires confirmation before cancelling and updates the row from the response', async () => {
    api.mockImplementation(async (path, options) => {
      if (path === '/api/admin/direct-play/settings') return { ...settings }
      if (path === '/api/admin/direct-play/tables') return { tables: [{ ...openTable }] }
      if (path === '/api/admin/direct-play/tables/7/cancel' && options?.method === 'POST') {
        return { ...openTable, status: 'cancelled' }
      }
      return null
    })
    const wrapper = view()
    await flushPromises()

    expect(api).not.toHaveBeenCalledWith('/api/admin/direct-play/tables/7/cancel', expect.anything())
    await wrapper.get('button[aria-label="Cancel / refund"]').trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    const confirm = wrapper.findAll('button').find(button => button.text() === 'Cancel and refund')
    await confirm!.trigger('click')
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/direct-play/tables/7/cancel', { method: 'POST' })
    await wrapper.get('button[aria-label="History (1)"]').trigger('click')
    expect(wrapper.text()).toContain('Cancelled')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
})
