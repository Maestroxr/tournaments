import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/services/api'
import { useI18n } from '@/i18n'
import TranzilaCheckoutAction from './TranzilaCheckoutAction.vue'

vi.mock('@/services/api', () => ({
  apiFetch: vi.fn(),
  formatApiError: (error: unknown) => error instanceof Error ? error.message : 'Request failed',
}))
const response = { method: 'POST', action: 'https://directng.tranzila.com/terminal/', fields: { sum: '30.00', tran: 'token' }, environment: 'test' }
const render = () => mount(TranzilaCheckoutAction, { props: { checkoutId: 'order/1' }, global: { stubs: {
  Button: { props: ['label', 'disabled', 'type'], template: '<button :type="type" :disabled="disabled">{{ label }}</button>' },
} } })

describe('TranzilaCheckoutAction', () => {
  beforeEach(() => { vi.mocked(apiFetch).mockReset(); useI18n().locale.value = 'he' })

  it('only prepares on click and requires a separate native form submission', async () => {
    const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => {})
    const requestSubmit = vi.spyOn(HTMLFormElement.prototype, 'requestSubmit').mockImplementation(() => {})
    vi.mocked(apiFetch).mockResolvedValue(response)
    const wrapper = render()
    expect(apiFetch).not.toHaveBeenCalled()
    expect(wrapper.find('form').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(apiFetch).toHaveBeenCalledWith('/api/admin/checkouts/order%2F1/session', { method: 'POST' })
    expect(wrapper.get('form').attributes()).toMatchObject({ action: response.action, method: 'POST', target: '_blank', rel: 'noopener noreferrer' })
    expect(wrapper.get('input[name="sum"]').attributes('value')).toBe('30.00')
    expect(wrapper.get('input[name="tran"]').attributes('type')).toBe('hidden')
    expect(wrapper.get('button').attributes('type')).toBe('submit')
    expect(wrapper.text()).toContain('פתיחת דף תשלום מאובטח')
    expect(wrapper.text()).toContain('סביבת בדיקות')
    expect(submit).not.toHaveBeenCalled()
    expect(requestSubmit).not.toHaveBeenCalled()
    submit.mockRestore(); requestSubmit.mockRestore()
  })

  it.each(['http://directng.tranzila.com/terminal', 'https://directng.tranzila.com.evil.test/terminal', 'javascript:alert(1)', 'https://user:secret@directng.tranzila.com/terminal'])('rejects unsafe action %s', async action => {
    vi.mocked(apiFetch).mockResolvedValue({ ...response, action })
    const wrapper = render()
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.get('[role="alert"]').text()).toContain('אינם תקינים')
  })

  it('displays errors, retries, labels live payments and resets when order changes', async () => {
    useI18n().locale.value = 'en'
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValueOnce({ ...response, environment: 'live' })
    const wrapper = render()
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('Unavailable')
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('real money payment')
    await wrapper.setProps({ checkoutId: 'order2' })
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.get('button').text()).toBe('Prepare Tranzila payment')
  })
})
