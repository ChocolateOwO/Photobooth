import type { components } from './schema'

export type HealthResponse = components['schemas']['HealthResponse']
export type VersionResponse = components['schemas']['VersionResponse']
export type KioskStatusResponse = components['schemas']['KioskStatusResponse']

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

  return {
    health: () => getJson<HealthResponse>('/api/health'),
    version: () => getJson<VersionResponse>('/api/version'),
    kioskStatus: () => getJson<KioskStatusResponse>('/api/kiosk/status'),
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
