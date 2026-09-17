import { describe, expect, it, vi } from 'vitest'

import { captureDeviceKeyFromFragment, createStorageDeviceKeyStore } from './deviceKey'

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
