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
