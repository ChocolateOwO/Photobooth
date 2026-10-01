import { describe, expect, it, vi } from 'vitest'

import {
  BOOTH_HEADER,
  boothHeaders,
  captureDeviceKeyFromFragment,
  createStorageDeviceKeyStore,
} from './deviceKey'
import { createApiClient } from './client'

const KEY = 'Ab3_-'.repeat(9)

function memoryStorage() {
  const data = new Map<string, string>()
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  }
}

describe('device key capture', () => {
  it('stores the key from the pairing fragment and strips it from the address bar', () => {
    const store = createStorageDeviceKeyStore('dummy', memoryStorage())
    const replaceState = vi.fn()
    const captured = captureDeviceKeyFromFragment(
      { hash: `#pair-key=${KEY}`, pathname: '/', search: '' },
      { replaceState },
      store,
    )
    expect(captured).toBe(true)
    expect(store.get()).toBe(KEY)
    expect(replaceState).toHaveBeenCalledWith(null, '', '/')
  })

  it('ignores ordinary fragments and malformed keys', () => {
    const store = createStorageDeviceKeyStore('dummy', memoryStorage())
    const replaceState = vi.fn()
    expect(
      captureDeviceKeyFromFragment({ hash: '#top', pathname: '/', search: '' }, { replaceState }, store),
    ).toBe(false)
    expect(replaceState).not.toHaveBeenCalled()
    expect(
      captureDeviceKeyFromFragment(
        { hash: '#pair-key=<script>', pathname: '/', search: '' },
        { replaceState },
        store,
      ),
    ).toBe(false)
    expect(replaceState).toHaveBeenCalledOnce() // the bad fragment is still removed
    expect(store.get()).toBeNull()
  })

  it('keeps Dummy and Main keys apart', () => {
    const storage = memoryStorage()
    createStorageDeviceKeyStore('dummy', storage).set(KEY)
    expect(createStorageDeviceKeyStore('main', storage).get()).toBeNull()
  })
})

describe('the booth id (Codex P8-001)', () => {
  it('is made once, kept through re-pairing, and names only this booth', () => {
    const storage = memoryStorage()
    const store = createStorageDeviceKeyStore('dummy', storage)
    const first = store.booth?.()
    expect(first).toMatch(/^[A-Za-z0-9_-]{22,64}$/)
    store.set(KEY)
    store.clear() // re-pairing drops the key...
    expect(store.booth?.()).toBe(first) // ...but the booth is still the same booth
    expect(createStorageDeviceKeyStore('dummy', storage).booth?.()).toBe(first)
    expect(createStorageDeviceKeyStore('dummy', memoryStorage()).booth?.()).not.toBe(first)
  })

  it('travels with every booth request, reads included', async () => {
    const store = createStorageDeviceKeyStore('dummy', memoryStorage())
    store.set(KEY)
    const seen: Record<string, string>[] = []
    const client = createApiClient(async (_path, init) => {
      seen.push(init?.headers as Record<string, string>)
      return new Response('null', { headers: { 'Content-Type': 'application/json' } })
    }, store)
    await client.currentSession()
    await client.giveUpSession('11111111-1111-4111-8111-111111111111')
    expect(seen.map((headers) => headers[BOOTH_HEADER])).toEqual([
      store.booth?.(),
      store.booth?.(),
    ])
    expect(boothHeaders({ get: () => null, set: () => undefined, clear: () => undefined })).toEqual(
      {},
    )
  })
})
