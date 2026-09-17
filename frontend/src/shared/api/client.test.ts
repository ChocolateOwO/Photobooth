import { describe, expect, it, vi } from 'vitest'

import { ApiError, createApiClient, type Fetcher } from './client'
import { DEVICE_KEY_HEADER, type DeviceKeyStore } from './deviceKey'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function memoryStore(initial: string | null): DeviceKeyStore & { value: string | null } {
  const store = {
    value: initial,
    get: () => store.value,
    set: (key: string) => {
      store.value = key
    },
    clear: () => {
      store.value = null
    },
  }
  return store
}

const KEY = 'k'.repeat(43)

describe('device mutations', () => {
  it('sends the stored device key with same-origin credentials and never asks the server for it', async () => {
    const fetcher = vi.fn<Fetcher>(async () => json({ ok: true }))
    const api = createApiClient(fetcher, memoryStore(KEY))

    await expect(api.boothPing()).resolves.toEqual({ ok: true })

    expect(fetcher).toHaveBeenCalledTimes(1)
    const [path, init] = fetcher.mock.calls[0] ?? []
    expect(path).toBe('/api/booth/ping')
    expect(init?.method).toBe('POST')
    expect(init?.credentials).toBe('same-origin')
    expect((init?.headers as Record<string, string>)[DEVICE_KEY_HEADER]).toBe(KEY)
  })

  it('refuses to send a mutation without a device key', async () => {
    const fetcher = vi.fn<Fetcher>(async () => json({ ok: true }))
    const api = createApiClient(fetcher, memoryStore(null))

    await expect(api.boothPing()).rejects.toBeInstanceOf(ApiError)
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('drops a rejected key so the kiosk must be re-paired', async () => {
    const store = memoryStore(KEY)
    const api = createApiClient(async () => json({ detail: 'device key invalid' }, 403), store)
    await expect(api.boothPing()).rejects.toEqual(expect.objectContaining({ status: 403 }))
    expect(store.value).toBeNull()
  })
})
