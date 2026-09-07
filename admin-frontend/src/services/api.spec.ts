import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ADMIN_NOTIFICATIONS_CHANGED_EVENT,
  ApiError,
  apiFetch,
} from './api'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

describe('apiFetch notification refresh events', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    fetchMock.mockReset()
    vi.unstubAllGlobals()
  })

  it('dispatches one refresh event after a successful mutation', async () => {
    const listener = vi.fn()
    window.addEventListener(ADMIN_NOTIFICATIONS_CHANGED_EVENT, listener)
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Saved' }))

    await apiFetch('/api/admin/tournaments/7/start', { method: 'POST' })

    expect(listener).toHaveBeenCalledTimes(1)
    window.removeEventListener(ADMIN_NOTIFICATIONS_CHANGED_EVENT, listener)
  })

  it('does not dispatch a refresh event after a GET request', async () => {
    const listener = vi.fn()
    window.addEventListener(ADMIN_NOTIFICATIONS_CHANGED_EVENT, listener)
    fetchMock.mockResolvedValueOnce(jsonResponse({ notifications: [] }))

    await apiFetch('/api/admin/notifications', { method: 'GET' })

    expect(listener).not.toHaveBeenCalled()
    window.removeEventListener(ADMIN_NOTIFICATIONS_CHANGED_EVENT, listener)
  })

  it('does not dispatch a refresh event after a failed mutation', async () => {
    const listener = vi.fn()
    window.addEventListener(ADMIN_NOTIFICATIONS_CHANGED_EVENT, listener)
    fetchMock.mockResolvedValueOnce(jsonResponse(
      { detail: 'Cannot start tournament' },
      { status: 412, statusText: 'Precondition Failed' },
    ))

    await expect(apiFetch('/api/admin/tournaments/7/start', { method: 'POST' }))
      .rejects.toBeInstanceOf(ApiError)

    expect(listener).not.toHaveBeenCalled()
    window.removeEventListener(ADMIN_NOTIFICATIONS_CHANGED_EVENT, listener)
  })
})
