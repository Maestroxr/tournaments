import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import UserCreateView from './UserCreateView.vue'
import { apiFetch, apiFieldErrors } from '@/services/api'
import { useI18n } from '@/i18n'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('@/services/api', () => ({
  apiFetch: vi.fn(),
  apiFieldErrors: vi.fn(() => ({})),
  formatApiError: (error: unknown) => error instanceof Error ? error.message : 'Request failed',
}))

const routerPush = vi.fn()
const apiFetchMock = vi.mocked(apiFetch)
const apiFieldErrorsMock = vi.mocked(apiFieldErrors)

const AppInputStub = defineComponent({
  name: 'AppInput',
  props: ['modelValue', 'label', 'type', 'error'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('label', [
      h('span', props.label),
      h('input', {
        'aria-label': props.label,
        type: props.type || 'text',
        value: props.modelValue,
        onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).value),
      }),
      props.error ? h('span', props.error) : null,
    ])
  },
})

const ButtonStub = defineComponent({
  name: 'ButtonStub',
  inheritAttrs: false,
  props: ['label', 'type'],
  emits: ['click'],
  setup(props, { attrs, emit }) {
    return () => h('button', { ...attrs, type: props.type || 'button', onClick: () => emit('click') }, props.label)
  },
})

const ToggleSwitchStub = defineComponent({
  name: 'ToggleSwitch',
  props: ['modelValue'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('input', {
      type: 'checkbox', checked: props.modelValue,
      onChange: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).checked),
    })
  },
})

const InputNumberStub = defineComponent({
  name: 'InputNumber',
  props: { modelValue: { type: Number, default: null } },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('input', {
      'aria-label': 'Opening balance amount',
      type: 'number',
      value: props.modelValue ?? '',
      onInput: (event: Event) => {
        const value = (event.target as HTMLInputElement).value
        emit('update:modelValue', value ? Number(value) : null)
      },
    })
  },
})

const WalletAdjustmentPanelStub = defineComponent({
  name: 'WalletAdjustmentPanel',
  props: {
    user: { type: Object, required: true },
    depositOnly: { type: Boolean, default: false },
  },
  template: '<div data-test="wallet-adjustment">{{ user.username }}:{{ depositOnly }}</div>',
})

function mountView() {
  return mount(UserCreateView, {
    global: { stubs: { AppInput: AppInputStub, AppAlert: true, Button: ButtonStub, InputNumber: InputNumberStub, ToggleSwitch: ToggleSwitchStub, WalletAdjustmentPanel: WalletAdjustmentPanelStub } },
  })
}

describe('UserCreateView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiFieldErrorsMock.mockReturnValue({})
    useI18n().locale.value = 'en'
    apiFetchMock.mockResolvedValue({ id: 12, username: 'dana', phone_number: '', is_staff: false, balance: '0.00' })
  })

  it('uses one password field while sending the backend confirmation value automatically', async () => {
    const wrapper = mountView()
    await wrapper.get('[aria-label="Username"]').setValue('dana')
    await wrapper.get('[aria-label="Phone number"]').setValue('0501234567')
    await wrapper.get('[aria-label="Password"]').setValue('Secure!Pass42')
    await wrapper.get('form').trigger('submit.prevent')

    expect(wrapper.find('[aria-label="Password confirmation"]').exists()).toBe(false)
    expect(apiFetchMock).toHaveBeenCalledWith('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        username: 'dana', phone_number: '0501234567', password1: 'Secure!Pass42', password2: 'Secure!Pass42', is_staff: false, initial_balance: 0,
      }),
    })
    expect(wrapper.text()).toContain('User created successfully')
    expect(wrapper.text()).toContain('Secure!Pass42')
    expect(wrapper.get('[data-test="wallet-adjustment"]').text()).toBe('dana:true')
  })

  it('creates the user with the opening balance entered in the form', async () => {
    const wrapper = mountView()
    await wrapper.get('[aria-label="Username"]').setValue('dana')
    await wrapper.get('[aria-label="Phone number"]').setValue('0501234567')
    await wrapper.get('[aria-label="Password"]').setValue('Secure!Pass42')
    await wrapper.get('[aria-label="Opening balance amount"]').setValue('75.5')
    await wrapper.get('form').trigger('submit.prevent')

    expect(apiFetchMock).toHaveBeenCalledWith('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        username: 'dana', phone_number: '0501234567', password1: 'Secure!Pass42', password2: 'Secure!Pass42', is_staff: false, initial_balance: 75.5,
      }),
    })
  })

  it('keeps the form in place and explains missing required fields', async () => {
    const wrapper = mountView()
    await wrapper.get('form').trigger('submit.prevent')

    expect(apiFetchMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Username required.')
    expect(wrapper.text()).toContain('Password required.')
  })

  it('accepts only English letters and numbers in the username', async () => {
    const wrapper = mountView()
    await wrapper.get('[aria-label="Username"]').setValue('דנה_12')
    await wrapper.get('[aria-label="Phone number"]').setValue('0501234567')
    await wrapper.get('[aria-label="Password"]').setValue('Secure!Pass42')
    await wrapper.get('form').trigger('submit.prevent')

    expect(apiFetchMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Use English letters and numbers only.')
  })

  it('sends the required phone number instead of email', async () => {
    const wrapper = mountView()
    await wrapper.get('[aria-label="Username"]').setValue('dana12')
    await wrapper.get('[aria-label="Phone number"]').setValue('050-123-4567')
    await wrapper.get('[aria-label="Password"]').setValue('Secure!Pass42')
    await wrapper.get('form').trigger('submit.prevent')

    const request = apiFetchMock.mock.calls[0]?.[1]
    expect(JSON.parse(String(request?.body))).toMatchObject({
      username: 'dana12',
      phone_number: '050-123-4567',
    })
    expect(JSON.parse(String(request?.body))).not.toHaveProperty('email')
  })

  it('shows backend password confirmation errors on the single password field', async () => {
    apiFetchMock.mockRejectedValueOnce(new Error('Invalid password'))
    apiFieldErrorsMock.mockReturnValueOnce({ password2: 'The password is too similar to the username.' })
    const wrapper = mountView()
    await wrapper.get('[aria-label="Username"]').setValue('maayan')
    await wrapper.get('[aria-label="Phone number"]').setValue('0501234567')
    await wrapper.get('[aria-label="Password"]').setValue('maayan12345')
    await wrapper.get('form').trigger('submit.prevent')

    expect(wrapper.text()).toContain('The password is too similar to the username.')
    expect(wrapper.get('[aria-label="Password"]').element).toBeTruthy()
  })
})
