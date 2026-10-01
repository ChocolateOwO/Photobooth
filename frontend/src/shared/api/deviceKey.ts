import type { InstanceName } from '../config/instance'

/**
 * The device key is the second pairing secret. It arrives once in the URL fragment of the pairing
 * redirect (fragments are never sent to servers) and is kept in this UI origin's storage, which no
 * other local origin can read. The HttpOnly device cookie alone never authorizes a mutation.
 */
export interface DeviceKeyStore {
  get(): string | null
  set(key: string): void
  clear(): void
  /**
   * This booth browser's own durable id: made once, kept through re-pairing (which renews the
   * cookie and the key). The server uses it to know which visits belong to this booth, so a
   * restart does not cut the booth off from the visit it was in the middle of.
   */
  booth?(): string | null
}

export const DEVICE_KEY_HEADER = 'X-Photobooth-Device-Key'
export const BOOTH_HEADER = 'X-Photobooth-Booth'
const FRAGMENT_PREFIX = '#pair-key='
const BOOTH_ID = /^[A-Za-z0-9_-]{22,64}$/

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function randomBoothId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(24))
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')
}

export function createStorageDeviceKeyStore(
  instance: InstanceName,
  storage: StorageLike = window.localStorage,
): DeviceKeyStore {
  const name = `photobooth.deviceKey.${instance}`
  const boothName = `photobooth.booth.${instance}`
  return {
    get: () => storage.getItem(name),
    set: (key) => storage.setItem(name, key),
    // Re-pairing replaces the key; the booth's own id stays (it names the booth, not a pairing).
    clear: () => storage.removeItem(name),
    booth: () => {
      try {
        const known = storage.getItem(boothName)
        if (known && BOOTH_ID.test(known)) return known
        const made = randomBoothId()
        storage.setItem(boothName, made)
        return made
      } catch {
        return null // no storage: the server names this browser by its pairing instead
      }
    },
  }
}

/** The headers every booth request carries besides its cookie. */
export function boothHeaders(store: DeviceKeyStore): Record<string, string> {
  const booth = store.booth?.()
  return booth ? { [BOOTH_HEADER]: booth } : {}
}

type LocationLike = Pick<Location, 'hash' | 'pathname' | 'search'>
type HistoryLike = Pick<History, 'replaceState'>

/** Moves a key from `#pair-key=...` into the store and removes it from the address bar. */
export function captureDeviceKeyFromFragment(
  location: LocationLike,
  history: HistoryLike,
  store: DeviceKeyStore,
): boolean {
  if (!location.hash.startsWith(FRAGMENT_PREFIX)) {
    return false
  }
  const key = decodeURIComponent(location.hash.slice(FRAGMENT_PREFIX.length))
  history.replaceState(null, '', `${location.pathname}${location.search}`)
  if (!/^[A-Za-z0-9_-]{40,}$/.test(key)) {
    return false
  }
  store.set(key)
  return true
}
