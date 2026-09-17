import { describe, expect, it, vi } from 'vitest'

import { ApiError, createApiClient, CSRF_HEADER, type Fetcher } from './client'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('device mutations', () => {
  it('sends the CSRF token read from kiosk status with same-origin credentials', async () => {
    const fetcher = vi.fn<Fetcher>(async (input) =>
      input === '/api/kiosk/status'
        ? json({ paired: true, csrf_token: 'a'.repeat(64) })
        : json({ ok: true }),
    )
    const api = createApiClient(fetcher)

    await expect(api.boothPing()).resolves.toEqual({ ok: true })

    const [path, init] = fetcher.mock.calls[1] ?? []
    expect(path).toBe('/api/booth/ping')
    expect(init?.method).toBe('POST')
    expect(init?.credentials).toBe('same-origin')
    expect((init?.headers as Record<string, string>)[CSRF_HEADER]).toBe('a'.repeat(64))
  })

  it('refuses to send a mutation when the kiosk is not paired', async () => {
    const fetcher = vi.fn<Fetcher>(async () => json({ paired: false, csrf_token: null }))
    const api = createApiClient(fetcher)

    await expect(api.boothPing()).rejects.toBeInstanceOf(ApiError)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('surfaces a server refusal as ApiError with its status', async () => {
    const fetcher = vi.fn<Fetcher>(async (input) =>
      input === '/api/kiosk/status'
        ? json({ paired: true, csrf_token: 'b'.repeat(64) })
        : json({ detail: 'origin not allowed' }, 403),
    )
    await expect(createApiClient(fetcher).boothPing()).rejects.toEqual(
      expect.objectContaining({ status: 403 }),
    )
  })
})
