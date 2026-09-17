import type { components } from './schema'

export type HealthResponse = components['schemas']['HealthResponse']
export type VersionResponse = components['schemas']['VersionResponse']
export type KioskStatusResponse = components['schemas']['KioskStatusResponse']
export type PingResponse = components['schemas']['PingResponse']

export const CSRF_HEADER = 'X-Photobooth-CSRF'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export type Fetcher = (input: string, init?: RequestInit) => Promise<Response>

/** Typed client for the kiosk API. Same-origin only; the device cookie travels automatically. */
export function createApiClient(fetcher: Fetcher = (input, init) => fetch(input, init)) {
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
   * Device-authenticated mutation. The browser adds the Origin header; the CSRF token comes from a
   * same-origin read of /api/kiosk/status (another origin cannot read that response).
   */
  async function postJson<T>(path: string, body?: unknown): Promise<T> {
    const status = await getJson<KioskStatusResponse>('/api/kiosk/status')
    if (!status.paired || !status.csrf_token) {
      throw new ApiError(401, 'kiosk is not paired')
    }
    const response = await fetcher(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        [CSRF_HEADER]: status.csrf_token,
      },
      body: body === undefined ? null : JSON.stringify(body),
    })
    if (!response.ok) {
      throw new ApiError(response.status, `POST ${path} failed with ${response.status}`)
    }
    return (await response.json()) as T
  }

  return {
    health: () => getJson<HealthResponse>('/api/health'),
    version: () => getJson<VersionResponse>('/api/version'),
    kioskStatus: () => getJson<KioskStatusResponse>('/api/kiosk/status'),
    boothPing: () => postJson<PingResponse>('/api/booth/ping'),
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
