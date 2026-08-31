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
  body: string
  constructor(status: number, statusText: string, body: string) {
    super(`${status} ${statusText}: ${body}`)
    this.status = status
    this.body = body
  }
}

export function formatApiError(e: unknown): string {
  if (e instanceof ApiError) {
    const statusText = e.statusText || ({ 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found', 412: 'Precondition Failed' } as Record<number, string>)[e.status] || ''
    const prefix = statusText ? `${e.status} ${statusText}` : String(e.status)
    try {
      const data = JSON.parse(e.body) as Record<string, unknown>
      const raw = (data.detail ?? data.errors ?? e.body) as unknown
      const detail = typeof raw === 'string' ? `"${raw}"` : JSON.stringify(raw)
      return `${prefix}: ${detail}`
    } catch {
      return e.message.includes(String(e.status)) ? e.message : `${prefix}: ${e.body}`
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
