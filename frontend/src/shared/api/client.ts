import { DEVICE_KEY_HEADER, type DeviceKeyStore } from './deviceKey'
import type { components } from './schema'

export type HealthResponse = components['schemas']['HealthResponse']
export type VersionResponse = components['schemas']['VersionResponse']
export type KioskStatusResponse = components['schemas']['KioskStatusResponse']
export type PingResponse = components['schemas']['PingResponse']

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export type Fetcher = (input: string, init?: RequestInit) => Promise<Response>

const noDeviceKey: DeviceKeyStore = { get: () => null, set: () => undefined, clear: () => undefined }

/** Typed client for the kiosk API. Same-origin only; the device cookie travels automatically. */
export function createApiClient(
  fetcher: Fetcher = (input, init) => fetch(input, init),
  deviceKeys: DeviceKeyStore = noDeviceKey,
) {
  async function getJson<T>(path: string): Promise<T> {
    const response = await fetcher(path, {
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    })
    if (!response.ok) {
      throw new ApiError(response.status, `GET ${path} failed with ${response.status}`)
    }
    return (await response.json()) as T
  }

  /**
   * Device-authenticated mutation: the browser adds Origin; the device key comes from this
   * origin's storage (captured at pairing), never from a server response.
   */
  async function postJson<T>(path: string, body?: unknown): Promise<T> {
    const key = deviceKeys.get()
    if (!key) {
      throw new ApiError(401, 'kiosk is not paired in this browser')
    }
    const response = await fetcher(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        [DEVICE_KEY_HEADER]: key,
      },
      body: body === undefined ? null : JSON.stringify(body),
    })
    if (response.status === 401 || response.status === 403) {
      deviceKeys.clear() // stale pairing (e.g. backend restarted): require re-pairing
    }
    if (!response.ok) {
      throw new ApiError(response.status, `POST ${path} failed with ${response.status}`)
    }
    return (await response.json()) as T
  }

  return {
    health: () => getJson<HealthResponse>('/api/health'),
    version: () => getJson<VersionResponse>('/api/version'),
    kioskStatus: () => getJson<KioskStatusResponse>('/api/kiosk/status'),
    hasDeviceKey: () => deviceKeys.get() !== null,
    boothPing: () => postJson<PingResponse>('/api/booth/ping'),
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
