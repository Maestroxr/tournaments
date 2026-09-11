import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PrimeVue from 'primevue/config'
import TransfersWorkspaceLayout from './TransfersWorkspaceLayout.vue'
import { useI18n } from '@/i18n'

const route = vi.hoisted(() => ({ name: 'transfers-finance' }))

vi.mock('vue-router', async importOriginal => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => route,
}))

describe('TransfersWorkspaceLayout', () => {
  beforeEach(() => {
    route.name = 'transfers-finance'
    useI18n().locale.value = 'en'
  })

  it('shows transactions and finance as sibling pages in the side menu', () => {
    const wrapper = mount(TransfersWorkspaceLayout, {
      global: {
        plugins: [PrimeVue],
        stubs: {
          RouterLink: { props: ['to'], template: '<a :data-to="to"><slot /></a>' },
          RouterView: { template: '<div data-router-view />' },
        },
      },
    })

    const links = wrapper.findAll('[data-to]')
    expect(links.map(link => link.attributes('data-to'))).toEqual([
      '/transfers',
      '/transfers/finance',
      '/transfers/payments',
      '/transfers/catalog',
    ])
    expect(links[1]?.classes()).toContain('is-selected')
    expect(links[1]?.attributes('aria-current')).toBe('page')
    expect(wrapper.find('[data-router-view]').exists()).toBe(true)
  })
})
