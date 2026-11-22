import { afterEach, describe, expect, it, vi } from 'vitest'
import openapi from '../../../docs/openapi.json'
import { ApiError, ENDPOINTS, api } from './client'
import { errorText } from '../lib/errors'

afterEach(() => vi.restoreAllMocks())
const res = (status: number, body: unknown) => ({ ok: status < 400, status, statusText: 'x', json: async () => body })

describe('api client', () => {
  it('maps the API error body to an ApiError with code and details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(409, { code: 'STALE_VERSION', message: 'stale', details: { expected: 1, actual: 2 } })))
    await expect(api.get('/api/x')).rejects.toMatchObject({ status: 409, code: 'STALE_VERSION', details: { expected: 1, actual: 2 } })
  })
  it('maps FastAPI detail-style errors too', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(404, { detail: { code: 'NOT_FOUND', message: 'no message m9' } })))
    await expect(api.get('/api/x')).rejects.toMatchObject({ code: 'NOT_FOUND', message: 'no message m9' })
  })
  it('a network failure says the API is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')))
    await expect(api.get('/api/x')).rejects.toMatchObject({ code: 'NETWORK' })
  })
  it('sends JSON for writes and nothing for reads', async () => {
    const f = vi.fn().mockResolvedValue(res(200, {})); vi.stubGlobal('fetch', f)
    await api.get('/api/a'); await api.post('/api/b', { x: 1 })
    expect(f.mock.calls[0][1].body).toBeUndefined()
    expect(f.mock.calls[1][1]).toMatchObject({ method: 'POST', body: '{"x":1}' })
  })
  it('every endpoint the client uses exists in the generated OpenAPI schema (no drift)', () => {
    const paths = Object.keys((openapi as { paths: Record<string, unknown> }).paths)
    for (const e of ENDPOINTS) expect(paths.some((p) => p === e || p.startsWith(`${e}/`)), `${e} missing from docs/openapi.json`).toBe(true)
  })
})

describe('errorText', () => {
  it('gives actionable wording for the cases a reviewer will hit', () => {
    expect(errorText(new ApiError(409, 'STALE_VERSION', 'x'))).toMatch(/changed since you opened/)
    expect(errorText(new ApiError(409, 'PREREQUISITE_PENDING', 'x'))).toMatch(/Accept the related suggestion first/)
    expect(errorText(new ApiError(422, 'UNRESOLVED_VALUE', 'x'))).toMatch(/Edit the suggestion/)
    expect(errorText(new ApiError(422, 'REFERENT_REQUIRED', 'x'))).toMatch(/Choose which task/)
    expect(errorText(new ApiError(400, 'OTHER', 'OTHER: something broke'))).toBe('something broke')
    expect(errorText(new Error('boom'))).toBe('boom')
  })
})
