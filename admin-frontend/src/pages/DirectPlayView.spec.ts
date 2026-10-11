import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import PrimeVue from 'primevue/config'
import Select from 'primevue/select'
import DirectPlayView from './DirectPlayView.vue'
import AdminNumberField from '@/components/game-settings/AdminNumberField.vue'
import { apiFetch, ApiError } from '@/services/api'
import { useI18n } from '@/i18n'
import type { DirectPlaySettings } from '@/types/directPlay'

vi.mock('@/services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api')>()),
  apiFetch: vi.fn<typeof apiFetch>(),
}))
const api = vi.mocked(apiFetch)
enableAutoUnmount(afterEach)
const rules = {
  enabled: true,
  target_points: [1, 3, 5, 7, 9],
  time_controls: ['none', 'normal', 'fast', 'slow'],
  doubling_options: [true, false],
}
const profile = {
  ...rules,
  public: true,
  private: true,
  quick: true,
  stake_amounts: [100, 500],
  fee_percent: 5,
  max_cube: 64,
  loss_limit_multiplier: 8,
  jacoby: false,
}
const settings: DirectPlaySettings = {
  format_profiles: {
    match: structuredClone(profile),
    money: { ...structuredClone(profile), target_points: [1], max_cube: 8, jacoby: true },
  },
  friend_rules: structuredClone(rules),
  practice_rules: { target_points: [1, 5, 7], time_controls: ['none', 'normal'] },
  money_time_control: 'normal',
  game_rules: {
    match: structuredClone(rules),
    friend: structuredClone(rules),
    quick: structuredClone(rules),
  },
  stake_amounts: [100, 500],
  enabled: true,
  friend_game_fee: '50.00',
  ai_game_fee: '50.00',
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
  template:
    '<div v-if="visible" role="dialog"><h2>{{ header }}</h2><slot /><slot name="footer" /></div>',
})
let router: ReturnType<typeof createRouter>
async function view(section = 'monitor') {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/direct-play', name: 'direct-play', component: DirectPlayView },
      { path: '/tournaments', name: 'tournaments', component: { template: '<div />' } },
    ],
  })
  await router.push({ name: 'direct-play', query: { section } })
  await router.isReady()
  const wrapper = mount(DirectPlayView, {
    global: { plugins: [PrimeVue, router], stubs: { Dialog: DialogStub } },
  })
  await flushPromises()
  return wrapper
}
async function section(value: string) {
  await router.push({ name: 'direct-play', query: { section: value } })
  await flushPromises()
}
const putBody = () =>
  JSON.parse(
    String(api.mock.calls.find(([, options]) => options?.method === 'PUT')?.[1]?.body),
  ) as Record<string, unknown>

describe('DirectPlayView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: false, addEventListener: vi.fn<() => void>(), removeEventListener: vi.fn<() => void>() })),
    )
    useI18n().locale.value = 'en'
    api.mockImplementation(async (path) =>
      path === '/api/admin/direct-play/settings'
        ? structuredClone(settings)
        : { tables: [{ ...openTable }] },
    )
  })
  it('switches game sections without losing a friend-price draft', async () => {
    const wrapper = await view('friend')
    wrapper.getComponent(AdminNumberField).vm.$emit('update:modelValue', 321)
    await section('monitor')
    expect(wrapper.get('#games-monitor').isVisible()).toBe(true)
    await section('friend')
    expect(wrapper.getComponent(AdminNumberField).props('modelValue')).toBe(321)
    expect(wrapper.text()).toContain('Unsaved changes')
    expect(wrapper.get('a[aria-current="page"]').text()).toContain('Play with a friend')
  })
  it('saves only the selected game and keeps a different section draft', async () => {
    const wrapper = await view('practice')
    wrapper.getComponent(AdminNumberField).vm.$emit('update:modelValue', 77)
    await section('friend')
    wrapper.getComponent(AdminNumberField).vm.$emit('update:modelValue', 75)
    api.mockImplementation(async (path, options) =>
      path === '/api/admin/direct-play/settings' && options?.method === 'PUT'
        ? { ...structuredClone(settings), friend_game_fee: '75.00' }
        : { tables: [] },
    )
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(putBody()).toEqual({
      section: 'friend',
      friend_rules: { ...rules, max_cube: 64 },
      friend_game_fee: 75,
    })
    await section('practice')
    expect(wrapper.getComponent(AdminNumberField).props('modelValue')).toBe(77)
    expect(wrapper.text()).toContain('Unsaved changes')
  })
  it('shows current game tables and labels friend pricing per target point', async () => {
    const wrapper = await view()
    expect(wrapper.text()).toContain('dana')
    expect(wrapper.text()).toContain('FRIEND')
    expect(wrapper.text()).toContain('no doubling')
    await section('friend')
    expect(wrapper.text()).toContain('Price per target point, per player')
    expect(wrapper.text()).toContain('price × target points')
  })
  it('adds and removes stakes only in the Match profile', async () => {
    const wrapper = await view('match')
    await wrapper.get('button[aria-label="Remove amount 100"]').trigger('click')
    wrapper
      .findAllComponents(AdminNumberField)
      .find((input) => input.props('label') === 'New amount')!
      .vm.$emit('update:modelValue', 750)
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((button) => button.text() === 'Add amount')!
      .trigger('click')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(putBody().section).toBe('match')
    expect(putBody().profile).toMatchObject({ stake_amounts: [500, 750] })
    expect(putBody()).not.toHaveProperty('format_profiles')
  })
  it('does not allow removing the last permitted clock', async () => {
    api.mockImplementation(async (path) =>
      path === '/api/admin/direct-play/settings'
        ? { ...structuredClone(settings), friend_rules: { ...rules, time_controls: ['none'] } }
        : { tables: [] },
    )
    const wrapper = await view('friend')
    const clocks = wrapper
      .findAllComponents({ name: 'AdminChoiceGroup' })
      .find((group) => group.props('label') === 'Clocks players may choose')!
    await clocks.get('button').trigger('click')
    expect(clocks.props('modelValue')).toEqual(['none'])
  })
  it('saves a fixed money clock and omits ineffective profile limits and access flags', async () => {
    const wrapper = await view('money')
    await wrapper.get('select').setValue('none')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(putBody()).toMatchObject({ section: 'money', money_time_control: 'none' })
    expect(putBody().profile).not.toHaveProperty('max_cube')
    expect(putBody().profile).not.toHaveProperty('loss_limit_multiplier')
    expect(putBody().profile).not.toHaveProperty('private')
    expect(wrapper.text()).toContain('calculated from the players’ balances')
  })
  it('refreshes monitoring without replacing unsaved settings', async () => {
    const wrapper = await view('friend')
    wrapper.getComponent(AdminNumberField).vm.$emit('update:modelValue', 321)
    await section('monitor')
    api.mockClear()
    const buttons = wrapper.findAll('button[aria-label="Refresh"]')
    await buttons[1]!.trigger('click')
    await flushPromises()
    expect(api).toHaveBeenCalledWith('/api/admin/direct-play/tables')
    expect(api).not.toHaveBeenCalledWith('/api/admin/direct-play/settings')
    await section('friend')
    expect(wrapper.getComponent(AdminNumberField).props('modelValue')).toBe(321)
  })
  it('keeps dirty settings when refreshing all data and updates pristine sections', async () => {
    const wrapper = await view('friend')
    wrapper.getComponent(AdminNumberField).vm.$emit('update:modelValue', 321)
    api.mockImplementation(async (path) =>
      path === '/api/admin/direct-play/settings'
        ? { ...structuredClone(settings), friend_game_fee: '99.00', ai_game_fee: '88.00' }
        : { tables: [] },
    )
    await wrapper.get('button[aria-label="Refresh"]').trigger('click')
    await flushPromises()
    expect(wrapper.getComponent(AdminNumberField).props('modelValue')).toBe(321)
    await section('practice')
    expect(wrapper.getComponent(AdminNumberField).props('modelValue')).toBe(88)
    expect(wrapper.text()).toContain('No unsaved changes')
  })
  it('keeps other drafts while a save is pending and blocks duplicate submissions', async () => {
    const wrapper = await view('friend')
    wrapper.getComponent(AdminNumberField).vm.$emit('update:modelValue', 75)
    let finish!: (value: DirectPlaySettings) => void
    api.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    await wrapper.get('form').trigger('submit')
    await wrapper.get('form').trigger('submit')
    expect(api.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(1)
    await section('practice')
    wrapper.getComponent(AdminNumberField).vm.$emit('update:modelValue', 88)
    finish({ ...structuredClone(settings), friend_game_fee: '75.00' })
    await flushPromises()
    expect(wrapper.getComponent(AdminNumberField).props('modelValue')).toBe(88)
    await section('friend')
    expect(wrapper.text()).toContain('No unsaved changes')
  })
  it('places server validation errors beside the tournament fee input', async () => {
    const wrapper = await view('tournaments')
    const input = wrapper.getComponent(AdminNumberField)
    expect(input.props('min')).toBe(8)
    expect(input.props('max')).toBe(10)
    input.vm.$emit('update:modelValue', 7)
    api.mockRejectedValueOnce(
      new ApiError(
        400,
        '',
        JSON.stringify({ errors: { tournament_fee_percent: ['Choose 8–10 percent'] } }),
      ),
    )
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(input.props('error')).toBe('Choose 8–10 percent')
    expect(wrapper.text()).toContain('Unsaved changes')
  })
  it('separates waiting players, paired games and history and filters quick matches', async () => {
    api.mockImplementation(async (path) => {
      if (path === '/api/admin/direct-play/settings') return { ...settings }
      return {
        tables: [
          { ...openTable, guest: null, status: 'open' },
          {
            ...openTable,
            id: 8,
            code: 'QUICK',
            mode: 'match',
            is_quick_match: true,
            status: 'ready',
          },
          { ...openTable, id: 9, code: 'PUBLIC', mode: 'match', status: 'playing' },
          { ...openTable, id: 10, code: 'DONE', status: 'completed', winner: 'dana' },
        ],
      }
    })
    const wrapper = await view()
    await flushPromises()
    expect(
      wrapper.findAll('[data-table-id]').map((row) => row.attributes('data-table-id')),
    ).toEqual(['7'])
    expect(wrapper.text()).toContain('Waiting for an opponent')
    await wrapper.get('button[aria-label="Paired / in progress (2)"]').trigger('click')
    wrapper
      .findAllComponents(Select)
      .find((component) =>
        component.props('options')?.some((option: { value: string }) => option.value === 'quick'),
      )!
      .vm.$emit('update:modelValue', 'quick')
    await flushPromises()
    expect(
      wrapper.findAll('[data-table-id]').map((row) => row.attributes('data-table-id')),
    ).toEqual(['8'])
    await wrapper.get('input[placeholder="Search player or table code"]').setValue('missing')
    expect(wrapper.findAll('[data-table-id]')).toHaveLength(0)
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
    const wrapper = await view()
    await flushPromises()

    expect(api).not.toHaveBeenCalledWith(
      '/api/admin/direct-play/tables/7/cancel',
      expect.anything(),
    )
    await wrapper.get('button[aria-label="Cancel / refund"]').trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    const confirm = wrapper
      .findAll('button')
      .find((button) => button.text() === 'Cancel and refund')
    await confirm!.trigger('click')
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/direct-play/tables/7/cancel', { method: 'POST' })
    await wrapper.get('button[aria-label="History (1)"]').trigger('click')
    expect(wrapper.text()).toContain('Cancelled')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
})
