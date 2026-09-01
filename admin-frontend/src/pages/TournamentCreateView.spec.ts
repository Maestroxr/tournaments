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
  formatApiError: (error: unknown) => error instanceof Error ? error.message : 'Request failed',
}))

const routerPush = vi.fn()
const apiFetchMock = vi.mocked(apiFetch)

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
    return () => h('label', [
      h('span', props.label),
      h('input', {
        placeholder: props.placeholder,
        value: props.modelValue,
        onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).value),
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
    return () => h('input', {
      value: formatValue(),
      onInput: (event: Event) => emit('update:modelValue', parseValue((event.target as HTMLInputElement).value)),
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
    return () => h('input', {
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
  emits: ['update:timeControl', 'update:targetPoints', 'update:doublingEnabled', 'update:entryFee', 'update:prizeMoney'],
  setup(props, { emit }) {
    return () => h('div', [
      h('input', {
        'aria-label': 'Match length',
        type: 'number',
        value: props.targetPoints,
        onInput: (event: Event) => emit('update:targetPoints', Number((event.target as HTMLInputElement).value)),
      }),
      h('select', {
        'aria-label': 'Time control',
        value: props.timeControl,
        onChange: (event: Event) => emit('update:timeControl', (event.target as HTMLSelectElement).value),
      }, [
        h('option', { value: 'normal' }, 'normal'),
        h('option', { value: 'speed' }, 'speed'),
      ]),
      h('input', {
        'aria-label': 'Doubling cube',
        type: 'checkbox',
        checked: props.doublingEnabled,
        onChange: (event: Event) => emit('update:doublingEnabled', (event.target as HTMLInputElement).checked),
      }),
      h('input', {
        'aria-label': 'Entry fee',
        type: 'number',
        value: props.entryFee,
        onInput: (event: Event) => emit('update:entryFee', Number((event.target as HTMLInputElement).value)),
      }),
      h('input', {
        'aria-label': 'Prize',
        type: 'number',
        value: props.prizeMoney,
        onInput: (event: Event) => emit('update:prizeMoney', Number((event.target as HTMLInputElement).value)),
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
    apiFetchMock.mockResolvedValue({ id: 8 })
  })

  it('defaults to a knockout draft and explains the generated structure', () => {
    const wrapper = mountView()

    expect(wrapper.text()).toContain('Create a tournament')
    expect(wrapper.text()).toContain('Knockout')
    expect(wrapper.text()).toContain('Selected')
    expect(wrapper.text()).toContain('The final bracket uses the actual player count at Start.')
    expect(wrapper.text()).toContain('5 matches')
    expect(wrapper.text()).toContain('3 rounds')
    expect(wrapper.text()).toContain('2 first-round byes')
  })

  it('shows validation errors and does not create a draft when required fields are invalid', async () => {
    const wrapper = mountView()

    await wrapper.find('form').trigger('submit.prevent')

    expect(apiFetchMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Review the highlighted fields before creating the draft.')
    expect(wrapper.text()).toContain('Enter a tournament name.')
  })

  it('creates a knockout tournament draft with normalized metadata', async () => {
    const wrapper = mountView()

    await inputAt(wrapper, 0).setValue('Friday Knockout')
    await inputAt(wrapper, 1).setValue('2027-01-10')
    await inputAt(wrapper, 2).setValue('19:30')
    await inputAt(wrapper, 3).setValue('8')
    await inputAt(wrapper, 4).setValue('16')
    await wrapper.find('form').trigger('submit.prevent')

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
      }),
    })
    expect(routerPush).toHaveBeenCalledWith({ name: 'tournament-detail', params: { id: 8 } })
  })

  it('updates the preview when player settings change', async () => {
    const wrapper = mountView()

    await inputAt(wrapper, 3).setValue('7')
    await nextTick()

    expect(wrapper.text()).toContain('6 matches')
    expect(wrapper.text()).toContain('1 first-round byes')
  })
})
