import { flushPromises, mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Popover from 'primevue/popover'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UserQuickView from './UserQuickView.vue'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(),
  apiFetch: vi.fn(),
}))

const api = vi.mocked(apiFetch)

describe('UserQuickView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useI18n().locale.value = 'he'
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders its details in a body-level overlay that cannot be clipped by a card', async () => {
    api.mockResolvedValue({
      id: 9,
      username: 'admin',
      phone_number: '',
      is_staff: false,
      is_active: true,
    })
    const wrapper = mount(UserQuickView, {
      attachTo: document.body,
      props: { userId: 9, username: 'admin' },
      global: {
        plugins: [PrimeVue],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })

    await wrapper.get('button').trigger('mouseenter')
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/users/9')
    expect(wrapper.getComponent(Popover).props('appendTo')).toBe('body')
    const card = document.body.querySelector<HTMLElement>('.user-quick-view')
    expect(card).not.toBeNull()
    expect(wrapper.element.contains(card)).toBe(false)
    expect(card?.closest('[role="dialog"]')?.getAttribute('dir')).toBe('ltr')
    expect(card?.getAttribute('dir')).toBe('rtl')
    expect(card?.textContent).toContain('admin')
    expect(card?.textContent).toContain('אין מספר טלפון')
    expect(card?.querySelector('.user-quick-view__edit')?.textContent).toContain('עריכת משתמש')

    wrapper.unmount()
  })

  it('opens only on hover, not on click or keyboard focus', async () => {
    api.mockResolvedValue({
      id: 9,
      username: 'admin',
      phone_number: '',
      is_staff: false,
      is_active: true,
    })
    const wrapper = mount(UserQuickView, {
      attachTo: document.body,
      props: { userId: 9, username: 'admin' },
      global: {
        plugins: [PrimeVue],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    const trigger = wrapper.get('button')

    await trigger.trigger('click')
    await trigger.trigger('focusin')
    await flushPromises()

    expect(api).not.toHaveBeenCalled()
    expect(document.body.querySelector('.user-quick-view')).toBeNull()

    await trigger.trigger('mouseenter')
    await flushPromises()

    expect(api).toHaveBeenCalledOnce()
    expect((wrapper.getComponent(Popover).vm as unknown as { target: Element }).target).toBe(trigger.element)
    expect(document.body.querySelector('.user-quick-view')).not.toBeNull()

    wrapper.unmount()
  })
})
