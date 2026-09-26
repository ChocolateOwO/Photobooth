import type { Fetcher } from './client'
import type { BoothSessionState, FrameMenu } from './client'
import { DEVICE_KEY_HEADER, type DeviceKeyStore } from './deviceKey'
import type { components } from './schema'

type Schemas = components['schemas']
/** Stored/edited settings: the theme is always complete (the API also accepts it omitted). */
export type ProfileSettings = Schemas['ProfileSettingsResponse']
/** What a create may send: the theme and the frame list may be left out (server defaults). */
export type NewProfileSettings = Schemas['ProfileSettingsBody']
export type EventTheme = Schemas['EventThemeBody']
export type ThemeCatalog = Schemas['ThemeCatalogResponse']
export type ThemePreset = Schemas['PresetInfo']
export type ThemeTokenInfo = Schemas['TokenInfo']
export type ContrastRule = Schemas['ContrastRuleInfo']
export type ExtractedTheme = Schemas['ExtractedTheme']
export type MainColours = Schemas['MainColoursResponse']
export type EventProfile = Schemas['EventProfileResponse']
export type MediaAsset = Schemas['MediaAssetResponse']
export type AssetKind = Schemas['AssetKind']
export type RetakeMode = Schemas['RetakeMode']
export type DeliveryMode = Schemas['DeliveryMode']
export type AdminSession = Schemas['SessionResponse']
export type TemplateSummary = Schemas['TemplateSummary']
export type Frame = Schemas['FrameResponse']
export type TemplateSpec = Schemas['TemplateSpec']

export const ADMIN_CSRF_HEADER = 'X-Photobooth-Admin-CSRF'

/** Limits enforced by the backend (Phase 3); the UI checks them first for friendlier messages. */
export const ASSET_LIMITS: Record<'logo' | 'background', { maxBytes: number; maxSide: number }> = {
  logo: { maxBytes: 5 * 1024 * 1024, maxSide: 4096 },
  background: { maxBytes: 12 * 1024 * 1024, maxSide: 7680 },
}
/** Only these two kinds are uploaded through /api/admin/assets; frames have their own routes. */
export type UploadableAssetKind = keyof typeof ASSET_LIMITS
export const ACCEPTED_IMAGE_TYPES = ['image/png', 'image/jpeg'] as const
export const INACTIVITY_LIMITS = { min: 30, max: 900 } as const
export const COUNTDOWN_LIMITS = { min: 1, max: 10, default: 5 } as const
/** Frame rules from the approved templates (the server checks them again). */
export const FRAME_LIMITS = { maxBytes: 10 * 1024 * 1024, mime: 'image/png' } as const
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

function withVersion(url: string, version: string | undefined): string {
  return version ? `${url}?v=${encodeURIComponent(version)}` : url
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
    /** Login, logout and session checks report auth failures to their caller instead of listeners. */
    quietAuth = false,
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
      } else if (kind === 'unauthenticated' && !quietAuth) {
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
      const session = await send<AdminSession>(
        'POST',
        '/api/admin/auth/login',
        { json: { username, password } },
        true,
      )
      csrfToken = session.csrf_token
      emit('signed-in')
      return session
    },
    /** Current session or null when signed out / expired. */
    async session(): Promise<AdminSession | null> {
      try {
        const session = await send<AdminSession>('GET', '/api/admin/auth/session', undefined, true)
        csrfToken = session.csrf_token
        return session
      } catch (error) {
        if (error instanceof AdminApiError && error.kind === 'unauthenticated') return null
        throw error
      }
    },
    /**
     * Resolves only once the server session is known to be gone (revoked now, or already expired).
     * Rejects when revocation could not be confirmed (network error, server error), so the UI never
     * shows "signed out" while the HttpOnly session cookie still works.
     */
    async logout(): Promise<void> {
      const revoke = () => send<undefined>('POST', '/api/admin/auth/logout', undefined, true)
      try {
        await revoke()
      } catch (error) {
        if (!(error instanceof AdminApiError) || error.kind !== 'unauthenticated') {
          throw error
        }
        if (error.status === 403) {
          // Stale CSRF token (e.g. rotated in another tab): re-read it from the live session, retry once.
          const live = await send<AdminSession>('GET', '/api/admin/auth/session', undefined, true).catch(
            (sessionError: unknown) => {
              if (sessionError instanceof AdminApiError && sessionError.kind === 'unauthenticated') {
                return null // already signed out on the server
              }
              throw sessionError
            },
          )
          if (live !== null) {
            csrfToken = live.csrf_token
            await revoke()
          }
        }
        // 401: no valid session any more, which is the goal of signing out.
      }
      csrfToken = null
      emit('signed-out')
    },

    templates: () => send<TemplateSummary[]>('GET', '/api/templates'),

    // --- Event themes: semantic colour tokens, presets, extraction from a background ---
    themeCatalog: () => send<ThemeCatalog>('GET', '/api/admin/themes'),
    /** Proposes a complete accessible theme from the background's colours (nothing is saved). */
    extractTheme: (backgroundAssetId: string) =>
      send<ExtractedTheme>('POST', '/api/admin/themes/extract', {
        json: { background_asset_id: backgroundAssetId },
      }),
    /** Every colour regenerated from the Button and Text colours (contrast kept; nothing saved). */
    mainColours: (tokens: Record<string, string>, button: string, text: string) =>
      send<MainColours>('POST', '/api/admin/themes/main-colours', { json: { tokens, button, text } }),

    listProfiles: (includeDeleted = false) =>
      send<EventProfile[]>('GET', `/api/admin/profiles${includeDeleted ? '?include_deleted=true' : ''}`),
    getProfile: (id: string) => send<EventProfile>('GET', profilePath(id)),
    createProfile: (settings: NewProfileSettings) =>
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

    // --- Frames (Phase 5): finished transparent PNGs made outside this app ---
    listFrames: (templateKey?: string) =>
      send<Frame[]>(
        'GET',
        `/api/admin/frames${templateKey ? `?template_key=${encodeURIComponent(templateKey)}` : ''}`,
      ),
    getFrame: (id: string) => send<Frame>('GET', `/api/admin/frames/${encodeURIComponent(id)}`),
    uploadFrame(templateKey: string, name: string, file: File): Promise<Frame> {
      const form = new FormData()
      form.append('template_key', templateKey)
      form.append('name', name)
      form.append('file', file)
      return send<Frame>('POST', '/api/admin/frames', { form })
    },
    replaceFrameFile(id: string, file: File): Promise<Frame> {
      const form = new FormData()
      form.append('file', file)
      return send<Frame>('POST', `/api/admin/frames/${encodeURIComponent(id)}/replace`, { form })
    },
    renameFrame: (id: string, name: string) =>
      send<Frame>('PUT', `/api/admin/frames/${encodeURIComponent(id)}/name`, { json: { name } }),
    deleteFrame: (id: string) =>
      send<undefined>('DELETE', `/api/admin/frames/${encodeURIComponent(id)}`),
    /**
     * The original PNG, for an <img> preview of the frame itself. Pass the frame's sha256 as
     * `version` so a replaced file gets a new URL and the browser never shows the old image.
     */
    frameContentUrl: (id: string, version?: string) =>
      withVersion(`/api/admin/frames/${encodeURIComponent(id)}/content`, version),
    /** A rendered sample output (placeholder photos + this frame); `version` as above. */
    framePreviewUrl: (id: string, outputIndex = 1, version?: string) =>
      withVersion(
        `/api/admin/frames/${encodeURIComponent(id)}/preview/${outputIndex}.jpg`,
        version,
      ),
    templateSpec: (key: string) =>
      send<TemplateSpec>('GET', `/api/templates/${encodeURIComponent(key)}`),
    templateGuideUrl: (key: string) => `/api/templates/${encodeURIComponent(key)}/guide.png`,
    templateBlankUrl: (key: string) => `/api/templates/${encodeURIComponent(key)}/blank.png`,

    uploadAsset(kind: AssetKind, file: File): Promise<MediaAsset> {
      const form = new FormData()
      form.append('kind', kind)
      form.append('file', file)
      return send<MediaAsset>('POST', '/api/admin/assets', { form })
    },
    getAsset: (id: string) => send<MediaAsset>('GET', `/api/admin/assets/${encodeURIComponent(id)}`),
    /** Same-origin image URL; the admin cookie authorizes it (usable directly in <img src>). */
    assetContentUrl: (id: string) => `/api/admin/assets/${encodeURIComponent(id)}/content`,

    // ---- "Test booth": the organizer tries a saved profile with the real camera -----------
    /** That profile's booth screens, exactly as a guest would see them. It is only read. */
    boothTestMenu: (profileId: string) =>
      send<FrameMenu>('GET', `/api/admin/booth-test/menu/${encodeURIComponent(profileId)}`),
    /** Start a test visit on that profile. It never becomes the active event. */
    startBoothTest: (profileId: string, idempotencyKey: string) =>
      send<BoothSessionState>('POST', '/api/admin/booth-test/sessions', {
        json: { profile_id: profileId, idempotency_key: idempotencyKey },
      }),
    /** Clear away test visits that are over or were left behind (never a guest's). */
    clearBoothTests: () => send<undefined>('POST', '/api/admin/booth-test/cleanup'),
  }
}

export type AdminApiClient = ReturnType<typeof createAdminApiClient>

/**
 * A new profile: the default preset theme and every photo size, so every frame (including later
 * uploads) is offered. 	heme comes from GET /api/admin/themes.
 */
export function newProfileSettings(theme: EventTheme, layouts: string[]): ProfileSettings {
  return {
    name: '',
    title: '',
    subtitle: '',
    start_button_text: 'Start',
    logo_asset_id: null,
    background_asset_id: null,
    theme,
    enabled_layouts: [...layouts],
    allow_surprise_me: false,
    countdown_seconds: COUNTDOWN_LIMITS.default,
    mirror: true,
    inactivity_timeout_s: 120,
    retake_mode: 'per_photo',
    delivery_mode: 'local_link',
  }
}
/** The theme of a preset, marked as chosen from that preset. */
export function presetTheme(preset: ThemePreset): EventTheme {
  return { tokens: { ...preset.tokens }, source: 'preset', preset: preset.id, palette: [] }
}
