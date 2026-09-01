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

const TournamentMetaFieldsStub = defineComponent({
  name: 'TournamentMetaFields',
  props: {
    timeControl: { type: String, required: true },
    targetPoints: { type: Number, required: true },
    rulesOnly: { type: Boolean, default: false },
    errors: { type: Object, default: () => ({}) },
  },
  emits: ['update:timeControl', 'update:targetPoints'],
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
    ])
  },
})

function mountView() {
  return mount(TournamentCreateView, {
    global: {
      stubs: {
        AppInput: AppInputStub,
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
