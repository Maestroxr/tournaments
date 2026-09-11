import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PrimeVue from 'primevue/config'
import CatalogView from './CatalogView.vue'
import { ApiError } from '@/services/api'
import { useI18n } from '@/i18n'

const api = vi.hoisted(() => vi.fn())
vi.mock('@/services/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/services/api')>(), apiFetch: api,
}))
const schema = {
  online_play: [false, true], tournaments: [false, true], weekly_cup: [false, true],
  monthly_cup: [false, true], grand_championship: [false, true], live_lessons: [false, true],
  vip_benefits: [false, true], rating: ['basic', 'full'], pr: ['none', 'basic', 'advanced', 'full'],
  analysis: ['none', 'basic', 'full'], courses: ['none', 'partial', 'full'], ai: ['limited', 'more', 'unlimited'],
}
const capabilities = {
  online_play: true, tournaments: true, weekly_cup: true, monthly_cup: false,
  grand_championship: false, live_lessons: false, vip_benefits: false,
  rating: 'full', pr: 'basic', analysis: 'basic', courses: 'partial', ai: 'more',
}
const plan = {
  id: 2, name: 'Gold', kind: 'subscription', tier: 'GOLD', price: '0.00', currency: 'ILS',
  coin_quantity: 0, period_months: 1, active: false, capabilities, version: 1,
}
const catalog = { items: [plan], capability_schema: schema }
function render() { return mount(CatalogView, { global: { plugins: [PrimeVue] } }) }
function writes() { return api.mock.calls.filter(call => call[1]?.method) }

describe('CatalogView', () => {
  beforeEach(() => {
    useI18n().locale.value = 'en'
    api.mockReset()
    api.mockImplementation((_url: string, options?: { method?: string }) =>
      Promise.resolve(options?.method ? plan : structuredClone(catalog)))
  })

  it('updates a seeded subscription with server version and all permission values', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.find('.product button').trigger('click')
    const editor = wrapper.find('form')
    await editor.find('input[type="number"]').setValue('39.90')
    await editor.find('input[type="checkbox"]').setValue(true)
    const analysis = editor.findAll('.permissions label').find(label => label.text().includes('Game analysis'))!
    await analysis.find('select').setValue('full')
    const lessons = editor.findAll('.permissions label').find(label => label.text().includes('Live lessons'))!
    await lessons.find('select').setValue('true')
    await editor.trigger('submit'); await flushPromises()
    expect(writes()).toHaveLength(1)
    const [url, options] = writes()[0]!
    expect(url).toBe('/api/admin/store-catalog/2')
    expect(options.method).toBe('PATCH')
    expect(JSON.parse(options.body)).toEqual({
      name: 'Gold', price: '39.9', currency: 'ILS', coin_quantity: 0, period_months: 1,
      active: true, version: 1, capabilities: { ...capabilities, analysis: 'full', live_lessons: true },
    })
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).toContain('Product saved successfully.')
  })

  it('creates a coin package with whole coin quantity and no subscription permissions', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.findAll('.tabs button')[1]!.trigger('click')
    await wrapper.find('.product-list > button').trigger('click')
    const editor = wrapper.find('form')
    await editor.find('input[maxlength]').setValue('Starter coins')
    const numbers = editor.findAll('input[type="number"]')
    await numbers[0]!.setValue('19.90')
    await numbers[1]!.setValue('500.5')
    expect(editor.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    await editor.trigger('submit'); await flushPromises()
    expect(writes()).toHaveLength(0)
    await numbers[1]!.setValue('500')
    await editor.find('input[type="checkbox"]').setValue(true)
    await editor.trigger('submit'); await flushPromises()
    expect(writes()).toHaveLength(1)
    const [url, options] = writes()[0]!
    expect(url).toBe('/api/admin/store-catalog')
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body)).toEqual({
      name: 'Starter coins', kind: 'coins', tier: '', price: '19.9', currency: 'ILS',
      coin_quantity: 500, period_months: 0, active: true, capabilities: {},
    })
  })

  it('blocks stale writes after a conflict until the current product is loaded', async () => {
    let currentPlan = plan
    api.mockImplementation((_url: string, options?: { method?: string }) => options?.method
      ? Promise.reject(new ApiError(409, 'Conflict', '{}'))
      : Promise.resolve(structuredClone({ ...catalog, items: [currentPlan] })))
    const wrapper = render(); await flushPromises()
    await wrapper.find('.product button').trigger('click')
    await wrapper.find('input[type="number"]').setValue('39.90')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('This product has changed')
    expect(wrapper.find('fieldset').attributes('disabled')).toBeDefined()
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(writes()).toHaveLength(1)
    currentPlan = { ...plan, price: '49.90', version: 2 }
    await wrapper.findAll('button').find(button => button.text() === 'Load latest version')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('fieldset').attributes('disabled')).toBeUndefined()
    expect((wrapper.find('input[type="number"]').element as HTMLInputElement).value).toBe('49.90')
    await wrapper.find('input[type="number"]').setValue('59.90')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(writes()).toHaveLength(2)
    expect(JSON.parse(writes()[1]![1].body)).toMatchObject({ version: 2, price: '59.9' })
  })
})
