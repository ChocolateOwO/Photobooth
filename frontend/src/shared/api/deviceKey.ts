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
}

export const DEVICE_KEY_HEADER = 'X-Photobooth-Device-Key'
const FRAGMENT_PREFIX = '#pair-key='

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

export function createStorageDeviceKeyStore(
  instance: InstanceName,
  storage: StorageLike = window.localStorage,
): DeviceKeyStore {
  const name = `photobooth.deviceKey.${instance}`
  return {
    get: () => storage.getItem(name),
    set: (key) => storage.setItem(name, key),
    clear: () => storage.removeItem(name),
  }
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
