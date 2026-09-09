import { mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import TournamentCreateView from './TournamentCreateView.vue'
import { apiFetch } from '@/services/api'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/services/api', () => ({
  apiFetch: vi.fn(),
  formatApiError: (error: unknown) => (error instanceof Error ? error.message : 'Request failed'),
}))

const routerPush = vi.fn()
const apiFetchMock = vi.mocked(apiFetch)
const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0))

const AppInputStub = defineComponent({
  name: 'AppInput',
  props: {
    modelValue: { type: String, default: '' },
    label: { type: String, required: true },
    placeholder: { type: String, default: '' },
    error: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () =>
      h('label', [
        h('span', props.label),
        h('input', {
          placeholder: props.placeholder,
          value: props.modelValue,
          onInput: (event: Event) =>
            emit('update:modelValue', (event.target as HTMLInputElement).value),
        }),
        props.error ? h('span', props.error) : null,
      ])
  },
})

const AppAlertStub = defineComponent({
  name: 'AppAlert',
  props: {
    message: { type: String, required: true },
  },
  setup(props) {
    return () => h('div', props.message)
  },
})

const DatePickerStub = defineComponent({
  name: 'DatePicker',
  props: {
    modelValue: { type: Date, default: null },
    timeOnly: { type: Boolean, default: false },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const pad = (value: number) => String(value).padStart(2, '0')
    const formatValue = () => {
      if (!(props.modelValue instanceof Date) || Number.isNaN(props.modelValue.getTime())) return ''
      return props.timeOnly
        ? `${pad(props.modelValue.getHours())}:${pad(props.modelValue.getMinutes())}`
        : `${props.modelValue.getFullYear()}-${pad(props.modelValue.getMonth() + 1)}-${pad(props.modelValue.getDate())}`
    }
    const parseValue = (value: string) => {
      if (!value) return null
      if (!props.timeOnly) {
        const [year = 0, month = 0, day = 0] = value.split('-').map(Number)
        return new Date(year, month - 1, day)
      }
      const [hours = 0, minutes = 0] = value.split(':').map(Number)
      const date = new Date()
      date.setHours(hours, minutes, 0, 0)
      return date
    }
    return () =>
      h('input', {
        value: formatValue(),
        onInput: (event: Event) =>
          emit('update:modelValue', parseValue((event.target as HTMLInputElement).value)),
      })
  },
})

const InputNumberStub = defineComponent({
  name: 'InputNumber',
  props: {
    modelValue: { type: Number, default: null },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () =>
      h('input', {
        type: 'number',
        value: props.modelValue ?? '',
        onInput: (event: Event) => {
          const value = (event.target as HTMLInputElement).value
          emit('update:modelValue', value === '' ? null : Number(value))
        },
      })
  },
})

const TournamentMetaFieldsStub = defineComponent({
  name: 'TournamentMetaFields',
  props: {
    timeControl: { type: String, required: true },
    targetPoints: { type: Number, required: true },
    doublingEnabled: { type: Boolean, default: true },
    entryFee: { type: Number, default: 0 },
    prizeMoney: { type: Number, default: 0 },
    rulesOnly: { type: Boolean, default: false },
    errors: { type: Object, default: () => ({}) },
  },
  emits: [
    'update:timeControl',
    'update:targetPoints',
    'update:doublingEnabled',
    'update:entryFee',
    'update:prizeMoney',
  ],
  setup(props, { emit }) {
    return () =>
      h('div', [
        h('input', {
          'aria-label': 'Match length',
          type: 'number',
          value: props.targetPoints,
          onInput: (event: Event) =>
            emit('update:targetPoints', Number((event.target as HTMLInputElement).value)),
        }),
        h(
          'select',
          {
            'aria-label': 'Time control',
            value: props.timeControl,
            onChange: (event: Event) =>
              emit('update:timeControl', (event.target as HTMLSelectElement).value),
          },
          [h('option', { value: 'normal' }, 'normal'), h('option', { value: 'speed' }, 'speed')],
        ),
        h('input', {
          'aria-label': 'Doubling cube',
          type: 'checkbox',
          checked: props.doublingEnabled,
          onChange: (event: Event) =>
            emit('update:doublingEnabled', (event.target as HTMLInputElement).checked),
        }),
        h('input', {
          'aria-label': 'Entry fee',
          type: 'number',
          value: props.entryFee,
          onInput: (event: Event) =>
            emit('update:entryFee', Number((event.target as HTMLInputElement).value)),
        }),
        h('input', {
          'aria-label': 'Prize',
          type: 'number',
          value: props.prizeMoney,
          onInput: (event: Event) =>
            emit('update:prizeMoney', Number((event.target as HTMLInputElement).value)),
        }),
      ])
  },
})

function mountView() {
  return mount(TournamentCreateView, {
    global: {
      stubs: {
        AppAlert: AppAlertStub,
        AppInput: AppInputStub,
        DatePicker: DatePickerStub,
        InputNumber: InputNumberStub,
        TournamentMetaFields: TournamentMetaFieldsStub,
      },
    },
  })
}

function inputAt(wrapper: VueWrapper, index: number): DOMWrapper<HTMLInputElement> {
  const input = wrapper.findAll<HTMLInputElement>('input')[index]
  if (!input) throw new Error(`Expected input at index ${index}`)
  return input
}

describe('TournamentCreateView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiFetchMock.mockImplementation(async (path, opts) => {
      if (path === '/api/admin/tournaments' && opts?.method === 'POST') return { id: 8 }
      if (path === '/api/admin/tournaments') return []
      if (path === '/api/admin/tournaments/8') return { id: 8, state: 'open' }
      return {}
    })
  })

  it('keeps future settings quiet until a preset is selected', async () => {
    const wrapper = mountView()

    expect(wrapper.text()).toContain('Create a tournament')
    expect(wrapper.text()).toContain('Quick setup · about one minute')
    expect(wrapper.find('nav[aria-label="Tournament setup"]').exists()).toBe(true)
    expect(wrapper.find('[aria-current="step"]').text()).toContain('Name and schedule')
    expect(wrapper.text()).not.toContain('tournamentCreate.steps.')
    expect(wrapper.text()).not.toContain('Done')
    expect(wrapper.text()).toContain('Choose in step 2')
    expect(wrapper.text()).not.toContain('Structure preview')

    const quickPreset = wrapper
      .findAll('button')
      .find((button) => button.text().includes('Quick cup'))
    if (!quickPreset) throw new Error('Expected quick preset button')
    await quickPreset.trigger('click')

    expect(quickPreset.attributes('aria-pressed')).toBe('true')
    expect(wrapper.text()).toContain('Knockout')
    expect(wrapper.text()).toContain('Structure preview')
    expect(wrapper.text()).toContain('5 matches')
    expect(wrapper.text()).toContain('3 rounds')
    expect(wrapper.text()).toContain('2 first-round byes')
  })

  it('shows validation errors and does not create a draft when required fields are invalid', async () => {
    const wrapper = mountView()

    await wrapper.find('form').trigger('submit.prevent')

    expect(apiFetchMock).not.toHaveBeenCalledWith(
      '/api/admin/tournaments',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(wrapper.text()).toContain('Review the highlighted fields before continuing.')
    expect(wrapper.text()).toContain('Enter a tournament name.')
  })

  it('creates a knockout tournament and opens registration with normalized metadata', async () => {
    const wrapper = mountView()

    await inputAt(wrapper, 0).setValue('Friday Knockout')
    await inputAt(wrapper, 1).setValue('2027-01-10')
    await inputAt(wrapper, 2).setValue('19:30')
    await wrapper.find('form').trigger('submit.prevent')
    expect(wrapper.find('[aria-pressed="true"]').text()).toContain('Knockout')
    await inputAt(wrapper, 0).setValue('8')
    await inputAt(wrapper, 1).setValue('16')
    await wrapper.find('form').trigger('submit.prevent')
    await wrapper.find('form').trigger('submit.prevent')
    expect(apiFetchMock).not.toHaveBeenCalledWith(
      '/api/admin/tournaments',
      expect.objectContaining({ method: 'POST' }),
    )
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(apiFetchMock).toHaveBeenCalledWith('/api/admin/tournaments', {
      method: 'POST',
      body: JSON.stringify({
        name: 'Friday Knockout',
        template: 'knockout',
        starts_at: '2027-01-10T19:30',
        min_players: 8,
        max_players: 16,
        target_points: 5,
        time_control: 'normal',
        doubling_enabled: true,
        entry_fee: 0,
        prize_money: 0,
        open_registration: true,
      }),
    })
    expect(routerPush).toHaveBeenCalledWith({ name: 'tournament-detail', params: { id: 8 } })
    expect(apiFetchMock).not.toHaveBeenCalledWith(
      '/api/admin/tournaments/8/publish',
      expect.anything(),
    )
  })

  it('opens registration when an older server creates a draft', async () => {
    let state = 'draft'
    apiFetchMock.mockImplementation(async (path, opts) => {
      if (path === '/api/admin/tournaments' && opts?.method === 'POST') return { id: 8, state }
      if (path === '/api/admin/tournaments/8/publish') {
        state = 'open'
        return { id: 8, state }
      }
      if (path === '/api/admin/tournaments/8') return { id: 8, state }
      return []
    })
    const wrapper = mountView()
    await inputAt(wrapper, 0).setValue('Club tournament')
    for (let step = 0; step < 4; step++) await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(apiFetchMock).toHaveBeenCalledWith('/api/admin/tournaments/8/publish', {
      method: 'POST',
    })
    expect(state).toBe('open')
    expect(routerPush).toHaveBeenCalledWith({ name: 'tournament-detail', params: { id: 8 } })
  })

  it('leaves the tournament start optional by default', async () => {
    const wrapper = mountView()
    await inputAt(wrapper, 0).setValue('Unscheduled tournament')

    for (let step = 0; step < 4; step++) await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const createCall = apiFetchMock.mock.calls.find(
      ([path, opts]) => path === '/api/admin/tournaments' && opts?.method === 'POST',
    )
    expect(createCall).toBeDefined()
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({ starts_at: null })
    expect(wrapper.text()).not.toContain('Start time must be now or in the future.')
  })

  it('keeps a saved tournament for retry when publishing fails, without creating a duplicate', async () => {
    let state = 'draft'
    let failPublish = true
    apiFetchMock.mockImplementation(async (path, opts) => {
      if (path === '/api/admin/tournaments' && opts?.method === 'POST') return { id: 8, state }
      if (path === '/api/admin/tournaments/8/publish') {
        if (failPublish) throw new Error('Publish unavailable')
        state = 'open'
        return { id: 8, state }
      }
      if (path === '/api/admin/tournaments/8') return { id: 8, state }
      return []
    })
    const wrapper = mountView()
    await inputAt(wrapper, 0).setValue('Club tournament')
    for (let step = 0; step < 4; step++) await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(routerPush).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Retry opening registration')
    failPublish = false
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    const creates = apiFetchMock.mock.calls.filter(
      ([path, opts]) => path === '/api/admin/tournaments' && opts?.method === 'POST',
    )
    expect(creates).toHaveLength(1)
    expect(routerPush).toHaveBeenCalledWith({ name: 'tournament-detail', params: { id: 8 } })
  })

  it('shows unique previous settings and groups exact duplicates', async () => {
    apiFetchMock.mockImplementation(async (path, opts) => {
      if (path === '/api/admin/tournaments' && opts?.method === 'POST') return { id: 8 }
      if (path === '/api/admin/tournaments')
        return [
          {
            id: 1,
            name: 'Monday Knockout',
            state: 'finished',
            min_players: 6,
            max_players: 16,
            target_points: 5,
            time_control: 'normal',
            doubling_enabled: true,
            entry_fee: '0.00',
            prize_money: '0.00',
          },
          {
            id: 2,
            name: 'Copy of Monday',
            state: 'finished',
            min_players: 6,
            max_players: 16,
            target_points: 5,
            time_control: 'normal',
            doubling_enabled: true,
            entry_fee: '0.00',
            prize_money: '0.00',
          },
          {
            id: 3,
            name: 'Fast Final',
            state: 'finished',
            min_players: 8,
            max_players: null,
            target_points: 7,
            time_control: 'fast',
            doubling_enabled: false,
            entry_fee: '10.00',
            prize_money: '50.00',
          },
        ]
      return {}
    })
    const wrapper = mountView()
    await flushPromises()

    await inputAt(wrapper, 0).setValue('New tournament')
    await wrapper.find('form').trigger('submit.prevent')
    await wrapper.find('form').trigger('submit.prevent')
    expect(wrapper.text()).toContain('Reuse a previous tournament setup')
    expect(wrapper.text()).toContain('Monday Knockout')
    expect(wrapper.text()).not.toContain('Copy of Monday')
    expect(wrapper.text()).toContain('Fast Final')
    expect(wrapper.text()).toContain('8–Unlimited players')
  })

  it('confirms when previous settings are applied', async () => {
    apiFetchMock.mockImplementation(async (path, opts) => {
      if (path === '/api/admin/tournaments' && opts?.method === 'POST') return { id: 8 }
      if (path === '/api/admin/tournaments')
        return [
          {
            id: 1,
            name: 'Monday Knockout',
            state: 'finished',
            min_players: 8,
            max_players: 16,
            target_points: 7,
            time_control: 'fast',
            doubling_enabled: false,
            entry_fee: '10.00',
            prize_money: '50.00',
          },
        ]
      return {}
    })
    const wrapper = mountView()
    await flushPromises()

    await inputAt(wrapper, 0).setValue('New tournament')
    await wrapper.find('form').trigger('submit.prevent')
    await wrapper.find('form').trigger('submit.prevent')
    const previousButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('Monday Knockout'))
    if (!previousButton) throw new Error('Expected previous tournament button')
    await previousButton.trigger('click')

    expect(wrapper.text()).toContain('Settings copied from Monday Knockout.')
    await wrapper.find('form').trigger('submit.prevent')
    expect(wrapper.text()).not.toContain('Settings copied from Monday Knockout.')
    expect(wrapper.text()).toContain('Create tournament & open registration')
    const back = wrapper.findAll('button').find((button) => button.text() === 'Back')
    if (!back) throw new Error('Expected back button')
    await back.trigger('click')
    await back.trigger('click')
    expect(wrapper.text()).not.toContain('Settings copied from Monday Knockout.')
    expect(inputAt(wrapper, 0).element.value).toBe('8')
    expect(inputAt(wrapper, 1).element.value).toBe('16')
  })

  it('updates the preview when player settings change', async () => {
    const wrapper = mountView()

    const quickPreset = wrapper
      .findAll('button')
      .find((button) => button.text().includes('Quick cup'))
    if (!quickPreset) throw new Error('Expected quick preset button')
    await quickPreset.trigger('click')
    await inputAt(wrapper, 3).setValue('7')
    await nextTick()

    expect(wrapper.text()).toContain('6 matches')
    expect(wrapper.text()).toContain('1 first-round byes')
  })
})
