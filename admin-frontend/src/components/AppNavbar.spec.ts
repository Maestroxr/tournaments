import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import PrimeVue from 'primevue/config'
import { describe, expect, it, vi } from 'vitest'
import AppNavbar from './AppNavbar.vue'
import AdminNotificationCenter from './AdminNotificationCenter.vue'
import { useAuthStore, type AuthUser } from '@/stores/auth'
import { apiFetch } from '@/services/api'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(),
  apiFetch: vi.fn().mockResolvedValue({}),
}))

async function renderNavbar(user: AuthUser | null) {
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.user = user
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
  it.each<[string, AuthUser | null, boolean]>([
    ['staff', { id: 1, username: 'admin', is_staff: true }, true],
    ['superuser', { id: 2, username: 'superuser', is_staff: false, is_superuser: true }, true],
    ['regular user', { id: 3, username: 'player', is_staff: false, is_superuser: false }, false],
    ['user without role flags', { id: 4, username: 'player' }, false],
    ['guest', null, false],
  ])('checks notification access for %s', async (_role, user, visible) => {
    const navbar = await renderNavbar(user)
    expect(navbar.findComponent(AdminNotificationCenter).exists()).toBe(visible)
    navbar.unmount()
    vi.mocked(apiFetch).mockClear()
  })
})
