import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UserEditView from './UserEditView.vue'
import UserAccountDetailsCard from '@/components/user/UserAccountDetailsCard.vue'
import UserAccessSettingsCard from '@/components/user/UserAccessSettingsCard.vue'
import UserPasswordCard from '@/components/user/UserPasswordCard.vue'
import { apiFetch, apiFieldErrors } from '@/services/api'
import { useI18n } from '@/i18n'

const routerPush = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '7' } }),
  useRouter: () => ({ push: routerPush }),
}))
vi.mock('@/services/api', () => ({
  apiFetch: vi.fn(),
  apiFieldErrors: vi.fn(() => ({})),
  formatApiError: (error: unknown) => error instanceof Error ? error.message : 'Request failed',
}))

const apiFetchMock = vi.mocked(apiFetch)
const apiFieldErrorsMock = vi.mocked(apiFieldErrors)
const user = {
  id: 7,
  username: 'maayan',
  phone_number: '050-123-4567',
  is_staff: false,
  is_active: true,
  balance: '25.00',
  transactions: [],
}

describe('UserEditView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useI18n().locale.value = 'en'
    apiFieldErrorsMock.mockReturnValue({})
    apiFetchMock.mockResolvedValue(user)
  })

  it('uses the shared account, password and permission components when saving', async () => {
    const wrapper = shallowMount(UserEditView)
    await flushPromises()

    wrapper.getComponent(UserAccountDetailsCard).vm.$emit('update:username', 'maayan2')
    wrapper.getComponent(UserAccountDetailsCard).vm.$emit('update:phoneNumber', '052-000-0000')
    wrapper.getComponent(UserPasswordCard).vm.$emit('update:modelValue', 'Strong!Pass42')
    wrapper.getComponent(UserAccessSettingsCard).vm.$emit('update:isStaff', true)
    await wrapper.get('form').trigger('submit.prevent')

    expect(apiFetchMock).toHaveBeenLastCalledWith('/api/admin/users/7', {
      method: 'PUT',
      body: JSON.stringify({
        username: 'maayan2',
        phone_number: '052-000-0000',
        is_staff: true,
        is_active: true,
        new_password: 'Strong!Pass42',
      }),
    })
    expect(routerPush).toHaveBeenCalledWith('/users')
  })

  it('passes backend password errors to the shared password component', async () => {
    apiFetchMock.mockResolvedValueOnce(user).mockRejectedValueOnce(new Error('Invalid password'))
    apiFieldErrorsMock.mockReturnValueOnce({ new_password: 'The password is too similar to the username.' })
    const wrapper = shallowMount(UserEditView)
    await flushPromises()

    wrapper.getComponent(UserPasswordCard).vm.$emit('update:modelValue', 'maayan12345')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.getComponent(UserPasswordCard).props('error')).toBe('The password is too similar to the username.')
  })
})
