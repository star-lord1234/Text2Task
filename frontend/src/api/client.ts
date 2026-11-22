export class ApiError extends Error {
  code: string
  status: number
  details?: Record<string, unknown> | null
  constructor(status: number, code: string, message: string, details?: Record<string, unknown> | null) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export const ENDPOINTS = [
  '/api/workspace', '/api/workspace/reset', '/api/messages', '/api/suggestions', '/api/tasks', '/api/dependencies', '/api/impact',
  '/api/scenarios', '/api/system/capabilities', '/api/settings', '/api/participants',
] as const

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, { method, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Cannot reach the API. Is the server running?')
  }
  if (!res.ok) {
    let data: any = null
    try { data = await res.json() } catch { /* not json */ }
    const d = data?.detail && !data?.code ? data.detail : data
    throw new ApiError(res.status, d?.code ?? 'ERROR', d?.message ?? res.statusText, d?.details ?? null)
  }
  return (await res.json()) as T
}

export const api = {
  get: <T,>(url: string) => request<T>('GET', url),
  post: <T,>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T,>(url: string, body: unknown) => request<T>('PUT', url, body),
  patch: <T,>(url: string, body: unknown) => request<T>('PATCH', url, body),
  del: <T,>(url: string) => request<T>('DELETE', url),
}
