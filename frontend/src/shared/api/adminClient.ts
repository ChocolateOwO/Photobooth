import type { Fetcher } from './client'
import { DEVICE_KEY_HEADER, type DeviceKeyStore } from './deviceKey'
import type { components } from './schema'

type Schemas = components['schemas']
export type ProfileSettings = Schemas['ProfileSettingsBody']
export type EventProfile = Schemas['EventProfileResponse']
export type MediaAsset = Schemas['MediaAssetResponse']
export type AssetKind = Schemas['AssetKind']
export type RetakeMode = Schemas['RetakeMode']
export type DeliveryMode = Schemas['DeliveryMode']
export type AdminSession = Schemas['SessionResponse']
export type TemplateSummary = Schemas['TemplateSummary']

export const ADMIN_CSRF_HEADER = 'X-Photobooth-Admin-CSRF'

/** Limits enforced by the backend (Phase 3); the UI checks them first for friendlier messages. */
export const ASSET_LIMITS: Record<AssetKind, { maxBytes: number; maxSide: number }> = {
  logo: { maxBytes: 5 * 1024 * 1024, maxSide: 4096 },
  background: { maxBytes: 12 * 1024 * 1024, maxSide: 7680 },
}
export const ACCEPTED_IMAGE_TYPES = ['image/png', 'image/jpeg'] as const
export const INACTIVITY_LIMITS = { min: 30, max: 900 } as const
export const TEXT_LIMITS = { name: 80, title: 120, subtitle: 240, startButtonText: 40 } as const

export type AdminErrorKind =
  | 'not-paired' // device cookie/key missing or rejected: re-pair the kiosk
  | 'unauthenticated' // no admin session, or it expired
  | 'not-found'
  | 'conflict' // stale revision, duplicate name, active profile, deleted profile
  | 'validation'
  | 'too-large'
  | 'unsupported'
  | 'throttled'
  | 'busy'
  | 'network'
  | 'server'

export class AdminApiError extends Error {
  readonly status: number
  readonly kind: AdminErrorKind
  /** Plain-language reasons from the server (one per problem when available). */
  readonly messages: string[]
  readonly retryAfterSeconds: number | null

  constructor(
    status: number,
    kind: AdminErrorKind,
    messages: string[],
    retryAfterSeconds: number | null = null,
  ) {
    super(messages[0] ?? `request failed (${status})`)
    this.name = 'AdminApiError'
    this.status = status
    this.kind = kind
    this.messages = messages
    this.retryAfterSeconds = retryAfterSeconds
  }
}

const DEVICE_DETAILS = new Set(['device not paired', 'origin not allowed', 'device key invalid'])

function detailMessages(body: unknown, splitProblems: boolean): string[] {
  if (typeof body !== 'object' || body === null || !('detail' in body)) {
    return []
  }
  const detail = (body as { detail: unknown }).detail
  if (typeof detail === 'string') {
    // Event Profile validation joins several problems with '; ' (HTTP 422 only).
    return splitProblems ? detail.split('; ').filter((part) => part.length > 0) : [detail]
  }
  if (Array.isArray(detail)) {
    return detail.map((item: unknown) => {
      if (typeof item === 'object' && item !== null && 'msg' in item) {
        const loc = 'loc' in item && Array.isArray(item.loc) ? item.loc.slice(1).join('.') : ''
        const msg = String((item as { msg: unknown }).msg)
        return loc ? `${loc}: ${msg}` : msg
      }
      return String(item)
    })
  }
  return []
}

function kindFor(status: number, messages: string[]): AdminErrorKind {
  const deviceProblem = messages.some((m) => DEVICE_DETAILS.has(m))
  if ((status === 401 || status === 403) && deviceProblem) return 'not-paired'
  if (status === 401 || status === 403) return 'unauthenticated'
  if (status === 404) return 'not-found'
  if (status === 409) return 'conflict'
  if (status === 413) return 'too-large'
  if (status === 415) return 'unsupported'
  if (status === 422) return 'validation'
  if (status === 429) return 'throttled'
  if (status === 503) return 'busy'
  return 'server'
}

export type SessionListener = (event: 'signed-in' | 'signed-out' | 'expired' | 'not-paired') => void

/**
 * Typed admin client. The admin session cookie is HttpOnly (Path=/api/admin); the per-session CSRF
 * token is kept only in memory and re-read from GET /api/admin/auth/session after a reload.
 */
export function createAdminApiClient(
  fetcher: Fetcher = (input, init) => fetch(input, init),
  deviceKeys: DeviceKeyStore,
) {
  let csrfToken: string | null = null
  const listeners = new Set<SessionListener>()
  const emit = (event: Parameters<SessionListener>[0]) => listeners.forEach((l) => l(event))

  async function send<T>(
    method: 'GET' | 'POST' | 'PUT' | 'DELETE',
    path: string,
    body?: { json: unknown } | { form: FormData },
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (method !== 'GET') {
      const key = deviceKeys.get()
      if (!key) {
        emit('not-paired')
        throw new AdminApiError(401, 'not-paired', ['This browser is not paired with the kiosk.'])
      }
      headers[DEVICE_KEY_HEADER] = key
      if (csrfToken) headers[ADMIN_CSRF_HEADER] = csrfToken
    }
    let payload: BodyInit | null = null
    if (body && 'json' in body) {
      headers['Content-Type'] = 'application/json'
      payload = JSON.stringify(body.json)
    } else if (body && 'form' in body) {
      payload = body.form // the browser sets the multipart boundary
    }
    let response: Response
    try {
      response = await fetcher(path, { method, headers, body: payload, credentials: 'same-origin' })
    } catch {
      throw new AdminApiError(0, 'network', ['The kiosk server could not be reached.'])
    }
    if (response.status === 204) {
      return undefined as T
    }
    let parsed: unknown
    try {
      parsed = await response.json()
    } catch {
      parsed = null
    }
    if (!response.ok) {
      const messages = detailMessages(parsed, response.status === 422)
      const kind = kindFor(response.status, messages)
      if (kind === 'not-paired') {
        deviceKeys.clear()
        csrfToken = null
        emit('not-paired')
      } else if (kind === 'unauthenticated' && !path.endsWith('/auth/login')) {
        const hadSession = csrfToken !== null
        csrfToken = null
        emit(hadSession ? 'expired' : 'signed-out')
      }
      const retryAfter = Number(response.headers.get('Retry-After'))
      throw new AdminApiError(
        response.status,
        kind,
        messages.length > 0 ? messages : [`Request failed (${response.status}).`],
        Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
      )
    }
    return parsed as T
  }

  const profilePath = (id: string) => `/api/admin/profiles/${encodeURIComponent(id)}`

  return {
    onSessionChange(listener: SessionListener): () => void {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    isPaired: () => deviceKeys.get() !== null,
    hasCsrfToken: () => csrfToken !== null,

    async login(username: string, password: string): Promise<AdminSession> {
      const session = await send<AdminSession>('POST', '/api/admin/auth/login', {
        json: { username, password },
      })
      csrfToken = session.csrf_token
      emit('signed-in')
      return session
    },
    /** Current session or null when signed out / expired. */
    async session(): Promise<AdminSession | null> {
      try {
        const session = await send<AdminSession>('GET', '/api/admin/auth/session')
        csrfToken = session.csrf_token
        return session
      } catch (error) {
        if (error instanceof AdminApiError && error.kind === 'unauthenticated') return null
        throw error
      }
    },
    async logout(): Promise<void> {
      try {
        await send<undefined>('POST', '/api/admin/auth/logout')
      } finally {
        csrfToken = null
        emit('signed-out')
      }
    },

    templates: () => send<TemplateSummary[]>('GET', '/api/templates'),

    listProfiles: (includeDeleted = false) =>
      send<EventProfile[]>('GET', `/api/admin/profiles${includeDeleted ? '?include_deleted=true' : ''}`),
    getProfile: (id: string) => send<EventProfile>('GET', profilePath(id)),
    createProfile: (settings: ProfileSettings) =>
      send<EventProfile>('POST', '/api/admin/profiles', { json: settings }),
    updateProfile: (id: string, settings: ProfileSettings, revision: number) =>
      send<EventProfile>('PUT', profilePath(id), { json: { ...settings, revision } }),
    duplicateProfile: (id: string, name?: string) =>
      send<EventProfile>('POST', `${profilePath(id)}/duplicate`, {
        json: name === undefined ? {} : { name },
      }),
    activateProfile: (id: string) => send<EventProfile>('POST', `${profilePath(id)}/activate`),
    deleteProfile: (id: string, revision: number) =>
      send<EventProfile>('DELETE', `${profilePath(id)}?revision=${revision}`),
    restoreProfile: (id: string) => send<EventProfile>('POST', `${profilePath(id)}/restore`),

    uploadAsset(kind: AssetKind, file: File): Promise<MediaAsset> {
      const form = new FormData()
      form.append('kind', kind)
      form.append('file', file)
      return send<MediaAsset>('POST', '/api/admin/assets', { form })
    },
    getAsset: (id: string) => send<MediaAsset>('GET', `/api/admin/assets/${encodeURIComponent(id)}`),
    /** Same-origin image URL; the admin cookie authorizes it (usable directly in <img src>). */
    assetContentUrl: (id: string) => `/api/admin/assets/${encodeURIComponent(id)}/content`,
  }
}

export type AdminApiClient = ReturnType<typeof createAdminApiClient>

/** Backend defaults for a new profile. `layouts` should come from GET /api/templates. */
export function newProfileSettings(layouts: string[]): ProfileSettings {
  return {
    name: '',
    title: '',
    subtitle: '',
    start_button_text: 'Start',
    logo_asset_id: null,
    background_asset_id: null,
    background_color: '#101418',
    primary_color: '#2F6FD6',
    secondary_color: '#FFB020',
    button_color: '#2F6FD6',
    text_color: '#F4F6F8',
    enabled_layouts: layouts.slice(0, 1),
    countdown_seconds: 5,
    mirror: true,
    inactivity_timeout_s: 120,
    retake_mode: 'per_photo',
    delivery_mode: 'local_link',
  }
}
