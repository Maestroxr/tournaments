import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import PrimeVue from 'primevue/config'
import Badge from 'primevue/badge'
import ToastService from 'primevue/toastservice'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminNotificationCenter from './AdminNotificationCenter.vue'
import {
  ADMIN_NOTIFICATIONS_CHANGED_EVENT,
  apiFetch,
} from '@/services/api'
import { useI18n } from '@/i18n'
import type { AdminNotificationsPayload } from '@/types/notifications'

vi.mock('@/services/api', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/api')>(),
  apiFetch: vi.fn(),
}))

const api = vi.mocked(apiFetch)
const payload: AdminNotificationsPayload = {
  updated_at: '2026-09-07T18:00:00Z',
  total: 2,
  counts: { critical: 0, warning: 1, info: 1 },
  notifications: [
    {
      notification_id: 'ready_to_start:20',
      id: 20,
      name: 'Ready Cup',
      state: 'open',
      starts_at: null,
      participant_count: 6,
      min_players: 6,
      max_players: 8,
      kind: 'ready_to_start',
      severity: 'info',
      message: 'server fallback',
      action_label: 'server fallback',
      action_to: '/tournaments/20/overview',
    },
    {
      notification_id: 'waiting_players:21',
      id: 21,
      name: 'Waiting Cup',
      state: 'open',
      starts_at: null,
      participant_count: 4,
      min_players: 6,
      max_players: 8,
      kind: 'waiting_players',
      severity: 'warning',
      message: 'server fallback',
      action_label: 'server fallback',
      action_to: '/tournaments/21/players',
    },
  ],
}

const newlyReadyNotification = {
  ...payload.notifications[0]!,
  notification_id: 'ready_to_start:22',
  id: 22,
  name: 'New Ready Cup',
  action_to: '/tournaments/22/overview',
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

async function renderCenter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/dashboard', component: { template: '<div />' } },
      { path: '/tournaments/:id/:section', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  return mount(AdminNotificationCenter, {
    attachTo: document.body,
    global: { plugins: [router, PrimeVue, ToastService] },
  })
}

describe('AdminNotificationCenter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useI18n().locale.value = 'en'
    api.mockResolvedValue(payload)
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('does not announce notifications that already exist on initial load', async () => {
    const wrapper = await renderCenter()
    await flushPromises()

    expect(document.body.querySelectorAll('.p-toast-message')).toHaveLength(0)
    wrapper.unmount()
  })

  it('announces a newly appearing notification once without duplicating it on later refreshes', async () => {
    const updatedPayload: AdminNotificationsPayload = {
      ...payload,
      total: 3,
      counts: { ...payload.counts, info: 2 },
      notifications: [...payload.notifications, newlyReadyNotification],
    }
    api
      .mockResolvedValueOnce(payload)
      .mockResolvedValueOnce(updatedPayload)
      .mockResolvedValueOnce(updatedPayload)

    const wrapper = await renderCenter()
    await flushPromises()
    expect(document.body.querySelectorAll('.p-toast-message')).toHaveLength(0)

    window.dispatchEvent(new Event(ADMIN_NOTIFICATIONS_CHANGED_EVENT))
    await flushPromises()

    const firstToast = document.body.querySelectorAll<HTMLElement>('.p-toast-message')
    expect(firstToast).toHaveLength(1)
    expect(firstToast[0]?.textContent).toContain('New Ready Cup')

    window.dispatchEvent(new Event(ADMIN_NOTIFICATIONS_CHANGED_EVENT))
    await flushPromises()

    expect(api).toHaveBeenCalledTimes(3)
    expect(document.body.querySelectorAll('.p-toast-message')).toHaveLength(1)
    wrapper.unmount()
  })

  it('announces a new notification when its event arrives during a non-announcing refresh', async () => {
    const pendingRefresh = deferred<AdminNotificationsPayload>()
    const updatedPayload: AdminNotificationsPayload = {
      ...payload,
      total: 3,
      counts: { ...payload.counts, info: 2 },
      notifications: [...payload.notifications, newlyReadyNotification],
    }
    api
      .mockResolvedValueOnce(payload)
      .mockReturnValueOnce(pendingRefresh.promise)
      .mockResolvedValueOnce(updatedPayload)

    const wrapper = await renderCenter()
    await flushPromises()

    await wrapper.get('[aria-haspopup="dialog"]').trigger('click')
    expect(api).toHaveBeenCalledTimes(2)

    window.dispatchEvent(new Event(ADMIN_NOTIFICATIONS_CHANGED_EVENT))
    pendingRefresh.resolve(updatedPayload)
    await flushPromises()

    const toasts = document.body.querySelectorAll<HTMLElement>('.p-toast-message')
    expect(api).toHaveBeenCalledTimes(3)
    expect(toasts).toHaveLength(1)
    expect(toasts[0]?.textContent).toContain('New Ready Cup')
    wrapper.unmount()
  })

  it('ignores an in-flight response and queued refresh after unmount', async () => {
    const pendingRefresh = deferred<AdminNotificationsPayload>()
    const updatedPayload: AdminNotificationsPayload = {
      ...payload,
      total: 3,
      counts: { ...payload.counts, info: 2 },
      notifications: [...payload.notifications, newlyReadyNotification],
    }
    api
      .mockResolvedValueOnce(payload)
      .mockReturnValueOnce(pendingRefresh.promise)
      .mockResolvedValue(updatedPayload)
    const wrapper = await renderCenter()
    const toastAdd = vi.spyOn(wrapper.vm.$toast, 'add')
    await flushPromises()
    window.dispatchEvent(new Event(ADMIN_NOTIFICATIONS_CHANGED_EVENT))
    window.dispatchEvent(new Event(ADMIN_NOTIFICATIONS_CHANGED_EVENT))
    expect(api).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    pendingRefresh.resolve(updatedPayload)
    await flushPromises()

    expect(api).toHaveBeenCalledTimes(2)
    expect(toastAdd).not.toHaveBeenCalled()
    expect(document.body.querySelectorAll('.p-toast-message')).toHaveLength(0)
    toastAdd.mockRestore()
  })

  it('shows the active count and actionable localized notifications', async () => {
    const wrapper = await renderCenter()
    await flushPromises()

    expect(api).toHaveBeenCalledWith('/api/admin/notifications')
    expect(wrapper.getComponent(Badge).props('value')).toBe('2')
    const trigger = wrapper.get('[aria-haspopup="dialog"]')
    expect(trigger.attributes('aria-label')).toContain('2 active')

    await trigger.trigger('click')
    await flushPromises()

    const panel = document.body.querySelector<HTMLElement>('.admin-notifications-panel')
    expect(panel).not.toBeNull()
    expect(panel?.getAttribute('role')).toBe('dialog')
    expect(panel?.textContent).toContain('Ready Cup')
    expect(panel?.textContent).toContain('6 players are registered')
    expect(panel?.textContent).toContain('Start tournament')
    expect(panel?.querySelector('a[href="/tournaments/20/overview"]')).not.toBeNull()
    expect(trigger.attributes('aria-expanded')).toBe('true')

    wrapper.unmount()
  })

  it('refreshes immediately after a successful admin mutation event', async () => {
    api.mockResolvedValueOnce(payload).mockResolvedValueOnce({
      ...payload,
      total: 0,
      counts: { critical: 0, warning: 0, info: 0 },
      notifications: [],
    })
    const wrapper = await renderCenter()
    await flushPromises()
    expect(wrapper.findComponent(Badge).exists()).toBe(true)

    window.dispatchEvent(new Event(ADMIN_NOTIFICATIONS_CHANGED_EVENT))
    await flushPromises()

    expect(api).toHaveBeenCalledTimes(2)
    expect(wrapper.findComponent(Badge).exists()).toBe(false)
    expect(wrapper.get('[aria-haspopup="dialog"]').attributes('aria-label')).toBe('Open notifications')
    wrapper.unmount()
  })

  it('shows a retryable error and an empty state', async () => {
    api.mockRejectedValue(new Error('offline'))
    const wrapper = await renderCenter()
    await flushPromises()
    await wrapper.get('[aria-haspopup="dialog"]').trigger('click')
    await flushPromises()

    expect(document.body.querySelector('[role="alert"]')?.textContent).toContain('Notifications could not be loaded')

    api.mockResolvedValue({
      ...payload,
      total: 0,
      counts: { critical: 0, warning: 0, info: 0 },
      notifications: [],
    })
    const retry = Array.from(document.body.querySelectorAll('button'))
      .find(button => button.textContent?.includes('Try again'))
    retry?.click()
    await flushPromises()

    expect(document.body.querySelector('.admin-notifications-panel')?.textContent).toContain('Everything is handled')
    wrapper.unmount()
  })
})
