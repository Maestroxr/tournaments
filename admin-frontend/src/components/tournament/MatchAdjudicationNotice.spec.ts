import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import MatchAdjudicationNotice from './MatchAdjudicationNotice.vue'
import { useI18n } from '@/i18n'

const wrappers: ReturnType<typeof mount>[] = []
function view(props: InstanceType<typeof MatchAdjudicationNotice>['$props'] = {}) {
  const wrapper = mount(MatchAdjudicationNotice, { props })
  wrappers.push(wrapper)
  return wrapper
}

describe('Recorded match incident', () => {
  beforeEach(() => {
    useI18n().locale.value = 'en'
  })
  afterEach(() => {
    wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  })

  it('renders Unix-second disconnect times by color without claiming current player presence', () => {
    const white = 1793620800
    const wrapper = view({
      absentSince: { white },
      occurredAt: '2026-11-02T12:01:00Z',
    })

    expect(wrapper.get('[data-absence-color="white"] time').attributes('datetime')).toBe(
      new Date(white * 1000).toISOString(),
    )
    expect(wrapper.get('[data-absence-color="white"]').text()).toContain('White')
    expect(wrapper.get('[data-absence-color="black"]').text()).toContain('Not recorded')
    expect(wrapper.text()).toContain('They do not indicate who is connected now.')
    expect(wrapper.text()).not.toContain('Dana')
    expect(wrapper.text()).not.toContain('Ben')
  })

  it('shows an explicit unknown value for missing, invalid and out-of-range dates', () => {
    const wrapper = view({
      absentSince: { white: Number.NaN, black: Number.MAX_VALUE },
      occurredAt: 'not a date',
    })
    expect(wrapper.findAll('time')).toHaveLength(0)
    expect(
      wrapper.findAll('[data-absence-color]').every((row) => row.text().includes('Not recorded')),
    ).toBe(true)
    expect(wrapper.text()).not.toContain('Invalid Date')
  })

  it('allows read-only form navigation before eligibility loads, locks rulings when unavailable, and blocks all shortcuts while busy', async () => {
    const wrapper = view()
    await wrapper.get('[data-incident-action="finish"]').trigger('click')
    expect(wrapper.emitted('action')).toEqual([['finish']])
    await wrapper.setProps({ canRule: false })
    for (const action of ['finish', 'advance', 'disqualify']) {
      expect(wrapper.get(`[data-incident-action="${action}"]`).attributes('disabled')).toBeDefined()
      await wrapper.get(`[data-incident-action="${action}"]`).trigger('click')
    }
    await wrapper.get('[data-incident-action="history"]').trigger('click')
    expect(wrapper.emitted('action')).toEqual([['finish'], ['history']])
    await wrapper.setProps({ disabled: true })
    expect(wrapper.get('[data-incident-action="history"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-incident-action="history"]').trigger('click')
    expect(wrapper.emitted('action')).toHaveLength(2)
  })

  it('updates the incident explanation and unknown dates when switching to Hebrew', async () => {
    const wrapper = view()
    useI18n().locale.value = 'he'
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('שני השחקנים איבדו חיבור')
    expect(wrapper.get('[data-absence-color="white"]').text()).toContain('לא תועד')
    expect(wrapper.get('[data-incident-action="finish"]').text()).not.toContain('Set final result')
  })
})
