const BASE = '' // use proxy: '' → '/api/...' hits Django via Vite

type FetchOpts = Omit<RequestInit, 'headers'> & { headers?: Record<string, string> }

function getCsrf(): string | undefined {
  return document.cookie
    .split('; ')
    .find((c) => c.startsWith('csrftoken='))
    ?.split('=')[1]
}

export class ApiError extends Error {
  status: number
  statusText: string
  body: string
  constructor(status: number, statusText: string, body: string) {
    super(`${status} ${statusText}: ${body}`)
    this.status = status
    this.statusText = statusText
    this.body = body
  }
}

function looksLikeHtml(value: string): boolean {
  return /<!doctype html|<html[\s>]|<body[\s>]|<h1[\s>]/i.test(value)
}

function friendlyStatusMessage(status: number, statusText: string): string {
  const label = statusText || ({
    400: 'Bad request',
    401: 'Please log in to continue.',
    403: 'You do not have permission to do that.',
    404: 'The requested page or action was not found.',
    405: 'This action is not available here. Try refreshing the page and signing in again.',
    500: 'The server had a problem. Please try again in a moment.',
  } as Record<number, string>)[status] || 'Request failed'

  return statusText ? `${status} ${label}` : label
}

export function formatApiError(e: unknown): string {
  if (e instanceof ApiError) {
    const fallback = friendlyStatusMessage(e.status, e.statusText)
    if (!e.body.trim() || looksLikeHtml(e.body)) return fallback
    try {
      const data = JSON.parse(e.body) as Record<string, unknown>
      const raw = (data.detail ?? data.errors ?? e.body) as unknown
      const detail = typeof raw === 'string' ? `"${raw}"` : JSON.stringify(raw)
      return `${fallback}: ${detail}`
    } catch {
      return e.body.length > 240 ? fallback : `${fallback}: ${e.body}`
    }
  }
  return e instanceof Error ? e.message : String(e)
}

export async function apiFetch<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (opts.headers) Object.assign(headers, opts.headers)
  const csrf = getCsrf()
  if (csrf && opts.method && opts.method !== 'GET') headers['X-CSRFToken'] = csrf
  const res = await fetch(path, { credentials: 'include', ...opts, headers })

  if (!res.ok) {
    const body = await res.text()
    throw new ApiError(res.status, res.statusText, body)
  }
  if (res.status === 204) return null as unknown as T
  return (await res.json()) as T
}
