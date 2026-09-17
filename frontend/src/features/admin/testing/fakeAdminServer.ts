import type {
  EventProfile,
  MediaAsset,
  ProfileSettings,
  TemplateSummary,
} from '../../../shared/api/adminClient'
import { ADMIN_CSRF_HEADER } from '../../../shared/api/adminClient'
import type { Fetcher } from '../../../shared/api/client'
import { DEVICE_KEY_HEADER } from '../../../shared/api/deviceKey'

export const DEVICE_KEY = 'k'.repeat(43)
const CSRF = 'c'.repeat(43)

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function template(key: string, name: string): TemplateSummary {
  return {
    key,
    name,
    version: 1,
    dpi: 300,
    width_in: 2,
    height_in: 6,
    width_px: 600,
    height_px: 1800,
    orientation: 'portrait',
    photos_per_output: 3,
    captures_per_session: 6,
    outputs_per_session: 2,
    links: { spec: '', blank_png: '', guide_png: '' },
  } as TemplateSummary
}

/**
 * In-memory stand-in for the Phase 3 admin API contract (same status codes and detail strings),
 * used by component tests. Real backend behaviour is covered by pytest and Playwright.
 */
export class FakeAdminServer {
  password = 'correct horse battery staple'
  signedIn = false
  throttleSeconds: number | null = null
  profiles = new Map<string, EventProfile>()
  assets = new Map<string, MediaAsset>()
  requests: { method: string; path: string; headers: Record<string, string> }[] = []
  templates = [template('strip_2x6', '2x6 photo strip'), template('print_4x6', '4x6 print')]
  private nextId = 1

  private id(): string {
    const n = String(this.nextId++).padStart(12, '0')
    return `00000000-0000-4000-8000-${n}`
  }

  seedProfile(settings: Partial<ProfileSettings> & { name: string }, extra: Partial<EventProfile> = {}) {
    const now = '2026-09-17T10:00:00Z'
    const profile: EventProfile = {
      id: this.id(),
      settings: {
        title: 'Welcome',
        subtitle: '',
        start_button_text: 'Start',
        logo_asset_id: null,
        background_asset_id: null,
        background_color: '#101418',
        primary_color: '#2F6FD6',
        secondary_color: '#FFB020',
        button_color: '#2F6FD6',
        text_color: '#F4F6F8',
        enabled_layouts: ['strip_2x6'],
        countdown_seconds: 5,
        mirror: true,
        inactivity_timeout_s: 120,
        retake_mode: 'per_photo',
        delivery_mode: 'local_link',
        ...settings,
      },
      is_active: false,
      revision: 1,
      created_at: now,
      updated_at: now,
      deleted_at: null,
      ...extra,
    }
    this.profiles.set(profile.id, profile)
    return profile
  }

  /** Simulates another admin tab saving the same profile. */
  bumpRevision(id: string, patch: Partial<ProfileSettings>) {
    const current = this.profiles.get(id)
    if (!current) throw new Error('unknown profile')
    this.profiles.set(id, {
      ...current,
      settings: { ...current.settings, ...patch },
      revision: current.revision + 1,
    })
  }

  readonly fetcher: Fetcher = async (input, init) => {
    const method = init?.method ?? 'GET'
    const headers = (init?.headers ?? {}) as Record<string, string>
    const url = new URL(input, 'http://127.0.0.1:5191')
    const path = url.pathname
    this.requests.push({ method, path: `${path}${url.search}`, headers })

    if (path === '/api/templates' && method === 'GET') return json(this.templates)
    if (!path.startsWith('/api/admin/')) return json({ detail: 'Not Found' }, 404)

    if (method !== 'GET' && headers[DEVICE_KEY_HEADER] !== DEVICE_KEY) {
      return json({ detail: 'device key invalid' }, 403)
    }
    if (path === '/api/admin/auth/login' && method === 'POST') {
      if (this.throttleSeconds !== null) {
        return json({ detail: 'too many failed logins; try again later' }, 429, {
          'Retry-After': String(this.throttleSeconds),
        })
      }
      const body = JSON.parse(String(init?.body)) as { username: string; password: string }
      if (body.username !== 'admin' || body.password !== this.password) {
        return json({ detail: 'invalid username or password' }, 401)
      }
      this.signedIn = true
      return json({ username: 'admin', csrf_token: CSRF, expires_in_seconds: 1800 })
    }
    if (!this.signedIn) return json({ detail: 'admin login required' }, 401)
    if (method !== 'GET' && headers[ADMIN_CSRF_HEADER] !== CSRF) {
      return json({ detail: 'admin csrf token invalid' }, 403)
    }
    if (path === '/api/admin/auth/session') {
      return json({ username: 'admin', csrf_token: CSRF, expires_in_seconds: 1800 })
    }
    if (path === '/api/admin/auth/logout') {
      this.signedIn = false
      return json(null, 204)
    }
    if (path === '/api/admin/assets' && method === 'POST') {
      const form = init?.body as FormData
      const file = form.get('file') as File
      const asset: MediaAsset = {
        id: this.id(),
        kind: form.get('kind') as MediaAsset['kind'],
        mime: file.type,
        width: 640,
        height: 480,
        bytes: file.size,
        sha256: 'a'.repeat(64),
        created_at: '2026-09-17T10:00:00Z',
      }
      this.assets.set(asset.id, asset)
      return json(asset, 201)
    }
    const assetMatch = /^\/api\/admin\/assets\/([^/]+)$/.exec(path)
    if (assetMatch) {
      const asset = this.assets.get(decodeURIComponent(assetMatch[1] ?? ''))
      return asset ? json(asset) : json({ detail: 'asset not found' }, 404)
    }
    if (path === '/api/admin/profiles') {
      if (method === 'GET') {
        const all = [...this.profiles.values()]
        const includeDeleted = url.searchParams.get('include_deleted') === 'true'
        return json(includeDeleted ? all : all.filter((p) => p.deleted_at === null))
      }
      const settings = JSON.parse(String(init?.body)) as ProfileSettings
      const clash = [...this.profiles.values()].some(
        (p) => p.deleted_at === null && p.settings.name.toLowerCase() === settings.name.toLowerCase(),
      )
      if (clash) return json({ detail: 'another live profile already uses this name' }, 409)
      return json(this.seedProfile(settings), 201)
    }
    const match = /^\/api\/admin\/profiles\/([^/]+)(?:\/(duplicate|activate|restore))?$/.exec(path)
    const profile = match ? this.profiles.get(match[1] ?? '') : undefined
    if (!match || !profile) return json({ detail: 'event profile not found' }, 404)
    const action = match[2]

    if (!action && method === 'GET') return json(profile)
    if (!action && method === 'PUT') {
      const body = JSON.parse(String(init?.body)) as ProfileSettings & { revision: number }
      if (body.revision !== profile.revision) {
        return json(
          {
            detail: `the profile was changed elsewhere (revision ${profile.revision}, expected ${body.revision}); reload and try again`,
          },
          409,
        )
      }
      const settings: ProfileSettings = { ...body }
      delete (settings as Partial<typeof body>).revision
      const updated = { ...profile, settings, revision: profile.revision + 1 }
      this.profiles.set(profile.id, updated)
      return json(updated)
    }
    if (!action && method === 'DELETE') {
      if (profile.is_active) {
        return json({ detail: 'the active profile can not be deleted; activate another profile first' }, 409)
      }
      const deleted = { ...profile, deleted_at: '2026-09-17T11:00:00Z', revision: profile.revision + 1 }
      this.profiles.set(profile.id, deleted)
      return json(deleted)
    }
    if (action === 'activate') {
      for (const p of this.profiles.values()) this.profiles.set(p.id, { ...p, is_active: p.id === profile.id })
      return json(this.profiles.get(profile.id))
    }
    if (action === 'duplicate') {
      return json(this.seedProfile({ ...profile.settings, name: `${profile.settings.name} (copy)` }), 201)
    }
    if (action === 'restore') {
      const restored = { ...profile, deleted_at: null, revision: profile.revision + 1 }
      this.profiles.set(profile.id, restored)
      return json(restored)
    }
    return json({ detail: 'Method Not Allowed' }, 405)
  }
}
