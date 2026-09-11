import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import AppTabs from './AppTabs.vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

describe('AppTabs', () => {
  it('links to the head-to-head admin page and marks it active', async () => {
    useI18n().locale.value = 'en'
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.user = { id: 1, username: 'admin', is_staff: true }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/direct-play', name: 'direct-play', component: { template: '<div />' } },
        { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
      ],
    })
    await router.push('/direct-play')
    await router.isReady()

    const wrapper = mount(AppTabs, { global: { plugins: [pinia, router] } })
    const link = wrapper.findAll('a').find(item => item.attributes('href') === '/direct-play')

    expect(link?.text()).toBe('Games')
    expect(link?.classes()).toContain('bg-dark')
  })
})
