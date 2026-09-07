import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppStepProgress from './AppStepProgress.vue'

const steps = [
  { id: 'details', label: 'Details' },
  { id: 'rules', label: 'Rules' },
  { id: 'review', label: 'Review' },
]

describe('AppStepProgress', () => {
  it('shows completed and current steps and emits selectable navigation', async () => {
    const wrapper = mount(AppStepProgress, {
      props: {
        steps,
        currentStep: 'review',
        completedSteps: ['details', 'rules'],
        selectableSteps: ['details', 'rules', 'review'],
        progressLabel: 'Step 3 of 3',
        label: 'Setup progress',
        interactive: true,
      },
    })

    expect(wrapper.get('nav').attributes('aria-label')).toBe('Setup progress')
    expect(wrapper.findAll('[data-pc-name="step"]')).toHaveLength(3)
    expect(wrapper.get('[aria-current="step"]').text()).toContain('Review')

    await wrapper.findAll('button')[0]?.trigger('click')
    expect(wrapper.emitted('select')).toEqual([['details']])
  })

  it('does not emit unavailable steps', async () => {
    const wrapper = mount(AppStepProgress, {
      props: {
        steps,
        currentStep: 'details',
        selectableSteps: ['details'],
        label: 'Setup progress',
        interactive: true,
      },
    })

    await wrapper.findAll('button')[1]?.trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
  })
})
