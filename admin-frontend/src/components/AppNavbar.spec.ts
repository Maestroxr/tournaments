import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import PrimeVue from 'primevue/config'
import { describe, expect, it, vi } from 'vitest'
import AppNavbar from './AppNavbar.vue'
import AdminNotificationCenter from './AdminNotificationCenter.vue'
import { useAuthStore } from '@/stores/auth'
import { apiFetch } from '@/services/api'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(),
  apiFetch: vi.fn().mockResolvedValue({}),
}))

async function renderNavbar(loggedIn: boolean) {
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.user = loggedIn ? { id: 1, username: 'admin', is_staff: true } : null
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/dashboard', component: { template: '<div />' } },
      { path: '/login', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  return mount(AppNavbar, {
    global: {
      plugins: [pinia, router, PrimeVue],
      stubs: {
        AppTabs: true,
        LanguageSwitcher: true,
        AdminNotificationCenter: { template: '<div data-testid="notification-center" />' },
      },
    },
  })
}

describe('AppNavbar', () => {
  it('shows the notification center only to a signed-in administrator', async () => {
    const signedIn = await renderNavbar(true)
    expect(signedIn.findComponent(AdminNotificationCenter).exists()).toBe(true)
    signedIn.unmount()

    const guest = await renderNavbar(false)
    expect(guest.findComponent(AdminNotificationCenter).exists()).toBe(false)
    guest.unmount()
    vi.mocked(apiFetch).mockClear()
  })
})
