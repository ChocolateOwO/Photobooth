import type {
  EventProfile,
  ExtractedTheme,
  Frame,
  MediaAsset,
  ProfileSettings,
  TemplateSummary,
} from '../../../shared/api/adminClient'
import { ADMIN_CSRF_HEADER, presetTheme } from '../../../shared/api/adminClient'
import type { Fetcher } from '../../../shared/api/client'
import { DEVICE_KEY_HEADER } from '../../../shared/api/deviceKey'
import { THEME_CATALOG } from './themeCatalog.fixture'

export const DEVICE_KEY = 'k'.repeat(43)
export const NO_SIZES =
  'No photo sizes are available to participants. Choose at least one photo size before this profile can be the active event.'
export const NO_FRAMES =
  'No frames exist for the chosen photo sizes. Choose another photo size or add a frame before this profile can be the active event.'

export const BUILTIN_FAMILIES = [
  ['minimal_light', 'Minimal Light'],
  ['midnight', 'Midnight'],
  ['celebration_gold', 'Celebration Gold'],
] as const

export function presetById(id: string) {
  const preset = THEME_CATALOG.presets.find((p) => p.id === id)
  if (!preset) throw new Error(`unknown preset ${id}`)
  return preset
}

/** The default preset theme, as the backend stores it for a new profile. */
export function defaultTheme() {
  return presetTheme(presetById(THEME_CATALOG.default_preset))
}

/** One shot of a booth visit, as the participant endpoints report it. */
interface BoothShot {
  shot_index: number
  attempt_no: number
  done: boolean
  capture_id: string | null
  version: string | null
}

interface BoothVisit {
  id: string
  is_test: boolean
  state: string
  state_version: number
  countdown_seconds: number
  mirror: boolean
  retake_mode: string
  inactivity_timeout_s: number
  expected_captures: number
  taken: number
  template_key: string | null
  layout_label: string | null
  frame_id: string | null
  shots: BoothShot[]
}

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function template(key: string, name: string): TemplateSummary {
  const strip = key === 'strip_2x6'
  return {
    key,
    name,
    version: 1,
    dpi: 300,
    width_in: strip ? 2 : 4,
    height_in: 6,
    width_px: strip ? 600 : 1200,
    height_px: 1800,
    orientation: 'portrait',
    photos_per_output: strip ? 3 : 4,
    captures_per_session: strip ? 6 : 4,
    outputs_per_session: strip ? 2 : 1,
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
  /** What the Admin "Test booth" page asked for, so tests can see it never activates anything. */
  boothTestMenus: string[] = []
  boothTestSessions: string[] = []
  boothTestCleanups = 0
  /** The test visit in progress, driven through the ordinary booth endpoints. */
  boothVisit: { visit: BoothVisit; profileId: string } | null = null
  throttleSeconds: number | null = null
  csrf = 'c'.repeat(43)
  /** When set, the upload response waits for this promise (simulates a slow upload). */
  uploadGate: Promise<void> | null = null
  /** When true, logout requests fail before reaching the server (network error). */
  logoutNetworkFailure = false
  profiles = new Map<string, EventProfile>()
  assets = new Map<string, MediaAsset>()
  frames = new Map<string, Frame>()
  /** Frame ids the server refuses to delete, with the reason (profiles still using them). */
  framesInUse = new Map<string, string>()
  /** How many frame-list requests fail with a server error before the list is served again. */
  frameListFailures = 0
  /** When set, the frame list waits for this promise (simulates a slow list). */
  frameListGate: Promise<void> | null = null
  /** Background asset ids colours were extracted from, in order. */
  extractedFrom: string[] = []
  /** Each extraction waits for the next gate in this list, if any (simulates slow answers). */
  extractGates: Promise<void>[] = []
  /** Per-background results; others get extractResult. */
  extractResults = new Map<string, ExtractedTheme>()
  /** Main-colour derivations requested, in order; each waits for the next gate, if any. */
  mainColourRequests: { button: string; text: string }[] = []
  mainColourGates: Promise<void>[] = []
  /** How many main-colour requests fail with a server error before they succeed again. */
  mainColourFailures = 0
  /** How many times the frame list was requested. */
  frameListRequests = 0
  /** When set, extraction fails with this plain reason (422). */
  extractFailure: string | null = null
  /** What extraction returns (a complete accessible theme with its swatches). */
  extractResult: ExtractedTheme = {
    tokens: { ...presetById('neon_party').tokens },
    source: 'extracted',
    preset: null,
    palette: ['#140B2E', '#D946EF', '#22D3EE'],
    message: 'Colors extracted from background',
  }
  requests: { method: string; path: string; headers: Record<string, string> }[] = []
  templates = [template('strip_2x6', '2x6 photo strip'), template('print_4x6', '4x6 print')]
  private nextId = 1

  constructor(options: { builtins?: boolean } = {}) {
    if (options.builtins ?? true) {
      for (const [family, name] of BUILTIN_FAMILIES) {
        for (const t of this.templates) {
          this.seedFrame(t.key, name, [], { builtin: true, family })
        }
      }
    }
  }

  /** The built-in frame of a family for a layout. */
  builtin(family: string, templateKey: string): Frame {
    const frame = [...this.frames.values()].find(
      (f) => f.builtin && f.family === family && f.template_key === templateKey,
    )
    if (!frame) throw new Error(`no built-in ${family} for ${templateKey}`)
    return frame
  }

  /** Frames an admin uploaded (the built-in library is always there). */
  customFrames(): Frame[] {
    return [...this.frames.values()].filter((f) => !f.builtin)
  }

  private id(): string {
    const n = String(this.nextId++).padStart(12, '0')
    return `00000000-0000-4000-8000-${n}`
  }

  seedFrame(
    templateKey: string,
    name: string,
    warnings: string[] = [],
    extra: Partial<Frame> = {},
  ): Frame {
    const frame: Frame = {
      id: this.id(),
      template_key: templateKey,
      template_version: 1,
      name,
      status: 'valid',
      width: templateKey === 'strip_2x6' ? 600 : 1200,
      height: 1800,
      bytes: 4096,
      sha256: 'b'.repeat(64),
      warnings,
      slot_transparency: [1, 1, 1],
      created_at: '2026-09-18T10:00:00Z',
      updated_at: '2026-09-18T10:00:00Z',
      builtin: false,
      family: null,
      ...extra,
    }
    this.frames.set(frame.id, frame)
    return frame
  }

  /** That profile's booth screens, as the admin booth-test endpoint returns them. */
  boothMenuFor(profile: EventProfile) {
    const frames = [...this.frames.values()]
      .filter(
        (frame) =>
          frame.status === 'valid' && profile.settings.enabled_layouts.includes(frame.template_key),
      )
      .map((frame) => ({
        id: frame.id,
        name: frame.name,
        preview_url: `/api/admin/frames/${frame.id}/preview/1.jpg`,
        plan: {
          frame_id: frame.id,
          template_key: frame.template_key,
          layout_label: frame.template_key === 'strip_2x6' ? '2×6' : '3×4',
          captures: frame.template_key === 'strip_2x6' ? 6 : 2,
          outputs: frame.template_key === 'strip_2x6' ? 2 : 1,
          photos_per_output: frame.template_key === 'strip_2x6' ? 3 : 2,
          output_capture_groups: frame.template_key === 'strip_2x6' ? [[1, 2, 3], [4, 5, 6]] : [[1, 2]],
          output_label: frame.template_key === 'strip_2x6' ? '2 strips' : null,
        },
      }))
    return {
      frames,
      layouts: [...new Set(frames.map((frame) => frame.plan.template_key))],
      allow_surprise_me: profile.settings.allow_surprise_me && frames.length >= 2,
      theme: profile.settings.theme.tokens,
      start_screen: {
        start_button_text: profile.settings.start_button_text,
        logo_url: null,
        background_url: null,
      },
      countdown_seconds: profile.settings.countdown_seconds,
    }
  }

  /** A test visit on that profile, as the admin booth-test endpoint returns it. */
  boothTestSession(profile: EventProfile) {
    const visit = {
      id: this.id(),
      is_test: true,
      state: 'eligibility_ok',
      state_version: 1,
      countdown_seconds: profile.settings.countdown_seconds,
      mirror: profile.settings.mirror,
      retake_mode: profile.settings.retake_mode,
      inactivity_timeout_s: profile.settings.inactivity_timeout_s,
      expected_captures: 0,
      taken: 0,
      template_key: null,
      layout_label: null,
      frame_id: null,
      shots: [] as BoothShot[],
    }
    // From here the test visit is an ordinary booth visit: the shared booth screens drive it
    // through the participant endpoints below, exactly as a guest's visit does.
    this.boothVisit = { visit, profileId: profile.id }
    return visit
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
        theme: defaultTheme(),
        enabled_layouts: this.templates.map((t) => t.key),
        allow_surprise_me: false,
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
    const stored = { ...profile, settings: { ...profile.settings, enabled_layouts: this.ordered(profile.settings.enabled_layouts) } }
    this.profiles.set(stored.id, stored)
    return stored
  }

  /** Profiles offering this frame's photo size (the Frames page shows them). */
  usedBy(frameId: string): string[] {
    const key = this.frames.get(frameId)?.template_key
    return [...this.profiles.values()]
      .filter((p) => key !== undefined && p.settings.enabled_layouts.includes(key))
      .map((p) => (p.deleted_at === null ? p.settings.name : `${p.settings.name} (deleted)`))
  }

  /** The server stores sizes in the template catalogue order. */
  private ordered(layouts: string[]): string[] {
    return this.templates.map((t) => t.key).filter((key) => layouts.includes(key))
  }

  /** Every built-in frame id, in library order (a new profile's default). */
  builtinIds(): string[] {
    return [...this.frames.values()].filter((f) => f.builtin).map((f) => f.id)
  }

  private badSizes(layouts: string[]): string | undefined {
    if (new Set(layouts).size !== layouts.length) return 'a photo size can be chosen only once'
    const unknown = layouts.filter((key) => !this.templates.some((t) => t.key === key))
    return unknown.length ? `unknown photo sizes: ${unknown.join(', ')}` : undefined
  }

  private validFrames(layouts: string[]): number {
    return [...this.frames.values()].filter((f) => layouts.includes(f.template_key) && f.status === 'valid').length
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
    // ---- "Test booth": a saved profile is read and tried, never activated or changed -------
    if (path.startsWith('/api/admin/booth-test/menu/') && method === 'GET') {
      if (!this.signedIn) return json({ detail: 'admin login required' }, 401)
      const profileId = path.slice('/api/admin/booth-test/menu/'.length)
      const profile = this.profiles.get(profileId)
      if (!profile) return json({ detail: 'no such profile' }, 404)
      this.boothTestMenus.push(profileId)
      return json(this.boothMenuFor(profile))
    }
    if (path === '/api/admin/booth-test/sessions' && method === 'POST') {
      if (!this.signedIn) return json({ detail: 'admin login required' }, 401)
      const asked = JSON.parse(String(init?.body)) as { profile_id: string }
      const profile = this.profiles.get(asked.profile_id)
      if (!profile) return json({ detail: 'no such profile' }, 404)
      this.boothTestSessions.push(asked.profile_id)
      return json(this.boothTestSession(profile), 201)
    }
    if (path === '/api/admin/booth-test/cleanup' && method === 'POST') {
      if (!this.signedIn) return json({ detail: 'admin login required' }, 401)
      this.boothTestCleanups += 1
      this.boothVisit = null
      return new Response(null, { status: 204 })
    }
    // ---- the visit itself: the same participant endpoints a guest's booth uses -------------
    if (path.startsWith('/api/booth/sessions')) {
      const held = this.boothVisit
      const rest = path.slice('/api/booth/sessions'.length)
      if (rest === '/current' && method === 'GET') return json(held?.visit ?? null)
      const action = /^\/([^/]+)(?:\/([a-z-]+))?$/.exec(rest)
      if (action && held && action[1] === held.visit.id) {
        const visit = held.visit
        if (!action[2] && method === 'GET') return json(visit)
        if (action[2] === 'frame' && method === 'POST') {
          const asked = JSON.parse(String(init?.body)) as { frame_id: string }
          const profile = this.profiles.get(held.profileId)
          const frame = profile
            ? this.boothMenuFor(profile).frames.find((f) => f.id === asked.frame_id)
            : undefined
          if (!frame) return json({ detail: 'no such frame' }, 404)
          visit.state = 'capturing'
          visit.state_version += 1
          visit.frame_id = frame.id
          visit.template_key = frame.plan.template_key
          visit.layout_label = frame.plan.layout_label
          visit.expected_captures = frame.plan.captures
          visit.shots = Array.from({ length: frame.plan.captures }, (_unused, index) => ({
            shot_index: index + 1,
            attempt_no: 1,
            done: false,
            capture_id: null,
            version: null,
          }))
          return json(visit)
        }
        if (action[2] === 'give-up' && method === 'POST') {
          visit.state = 'gave_up'
          visit.state_version += 1
          return json(visit)
        }
      }
      return json({ detail: 'no such session' }, 404)
    }

    if (path === '/api/admin/themes' && method === 'GET' && this.signedIn) {
      return json(THEME_CATALOG)
    }
    const specMatch = /^\/api\/templates\/([a-z0-9_]+)$/.exec(path)
    if (specMatch && method === 'GET') {
      const template = this.templates.find((t) => t.key === specMatch[1])
      if (!template) return json({ detail: 'template not found' }, 404)
      const strip = template.key === 'strip_2x6'
      return json({
        ...template,
        bleed: 0,
        safe_area_inset: 30,
        safe_area: { x: 30, y: 30, w: template.width_px - 60, h: template.height_px - 60 },
        branding_area: strip ? { x: 30, y: 1590, w: 540, h: 180 } : null,
        slots: [1, 2, 3].map((index) => ({
          index,
          x: 30,
          y: 60 + (index - 1) * 510,
          w: template.width_px - 60,
          h: 480,
          aspect: strip ? '6:5' : '3:2',
          fit: 'cover',
          anchor: 'center',
        })),
        output_capture_groups: strip ? [[1, 2, 3], [4, 5, 6]] : [[1, 2, 3, 4]],
        frame_rules: {
          format: 'PNG',
          mode: 'RGBA',
          color: 'sRGB',
          animated: false,
          exact_size: true,
          max_bytes: 10 * 1024 * 1024,
          slot_min_transparency: 0.95,
        },
        frame_requirements: [
          `File: PNG with transparency (RGBA), not animated.`,
          `Size: exactly ${template.width_px} x ${template.height_px} px.`,
        ],
      })
    }
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
      return json({ username: 'admin', csrf_token: this.csrf, expires_in_seconds: 1800 })
    }
    if (path === '/api/admin/auth/logout' && this.logoutNetworkFailure) {
      throw new TypeError('Failed to fetch')
    }
    if (!this.signedIn) return json({ detail: 'admin login required' }, 401)
    if (method !== 'GET' && headers[ADMIN_CSRF_HEADER] !== this.csrf) {
      return json({ detail: 'admin csrf token invalid' }, 403)
    }
    if (path === '/api/admin/auth/session') {
      return json({ username: 'admin', csrf_token: this.csrf, expires_in_seconds: 1800 })
    }
    if (path === '/api/admin/auth/logout') {
      this.signedIn = false
      return json(null, 204)
    }
    if (path === '/api/admin/assets' && method === 'POST') {
      if (this.uploadGate) await this.uploadGate
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
    if (path === '/api/admin/frames') {
      if (method === 'GET') {
        this.frameListRequests += 1
        if (this.frameListGate) await this.frameListGate
        if (this.frameListFailures > 0) {
          this.frameListFailures -= 1
          return json({ detail: 'internal error' }, 500)
        }
        const templateKey = url.searchParams.get('template_key')
        const all = [...this.frames.values()].map((f) => ({ ...f, used_by: this.usedBy(f.id) }))
        return json(templateKey ? all.filter((f) => f.template_key === templateKey) : all)
      }
      const form = init?.body as FormData
      const templateKey = String(form.get('template_key'))
      const name = String(form.get('name')).trim()
      const file = form.get('file') as File
      if (!this.templates.some((t) => t.key === templateKey)) {
        return json({ detail: `Unknown photo layout '${templateKey}'.` }, 422)
      }
      if (file.type !== 'image/png') {
        return json({ detail: 'The frame must be a valid PNG file.' }, 422)
      }
      if ([...this.frames.values()].some((f) => f.template_key === templateKey && f.name === name)) {
        return json({ detail: `A frame called '${name}' already exists for this layout.` }, 422)
      }
      return json(this.seedFrame(templateKey, name), 201)
    }
    if (path === '/api/admin/themes/main-colours' && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as { tokens: Record<string, string>; button: string; text: string }
      this.mainColourRequests.push({ button: body.button, text: body.text })
      const gate = this.mainColourGates.shift()
      if (gate) await gate
      if (this.mainColourFailures > 0) {
        this.mainColourFailures -= 1
        return json({ detail: 'internal error' }, 500)
      }
      // A stand-in for the server's derivation: the two colours and some of their related shades.
      const tokens = {
        ...body.tokens,
        primary_bg: body.button,
        primary_hover: body.button,
        primary_pressed: body.button,
        link: body.button,
        focus_ring: body.button,
        heading: body.text,
        body: body.text,
        input_text: body.text,
      }
      return json({ tokens, button: body.button, text: body.text })
    }
    if (path === '/api/admin/themes/extract' && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as { background_asset_id: string }
      this.extractedFrom.push(body.background_asset_id)
      const gate = this.extractGates.shift()
      if (gate) await gate
      if (this.extractFailure) return json({ detail: this.extractFailure }, 422)
      return json(this.extractResults.get(body.background_asset_id) ?? this.extractResult)
    }
    const frameMatch = /^\/api\/admin\/frames\/([^/]+)(?:\/(replace|name))?$/.exec(path)
    if (frameMatch) {
      const frame = this.frames.get(frameMatch[1] ?? '')
      if (!frame) return json({ detail: 'frame not found' }, 404)
      const action = frameMatch[2]
      if (!action && method === 'GET') return json({ ...frame, used_by: this.usedBy(frame.id) })
      if (frame.builtin) {
        return json(
          {
            detail:
              'Built-in frames can not be changed or deleted. Upload your own frame to use a different design.',
          },
          409,
        )
      }
      if (!action && method === 'DELETE') {
        // Profiles offer sizes, so a frame is never blocked by them; tests may still force a refusal.
        const reason = this.framesInUse.get(frame.id)
        if (reason) {
          return json({ detail: `this frame is still used by: ${reason}` }, 409)
        }
        this.frames.delete(frame.id)
        return json(null, 204)
      }
      if (action === 'replace') {
        const file = (init?.body as FormData).get('file') as File
        if (file.type !== 'image/png') {
          return json({ detail: 'The frame must be a valid PNG file.' }, 422)
        }
        const updated = { ...frame, bytes: file.size, sha256: 'c'.repeat(64) }
        this.frames.set(frame.id, updated)
        return json(updated)
      }
      if (action === 'name' && method === 'PUT') {
        const body = JSON.parse(String(init?.body)) as { name: string }
        const name = body.name.trim()
        if (!name) return json({ detail: 'The frame name must be 1-80 characters.' }, 422)
        const updated = { ...frame, name }
        this.frames.set(frame.id, updated)
        return json(updated)
      }
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
      settings.enabled_layouts = settings.enabled_layouts ?? this.templates.map((t) => t.key)
      settings.countdown_seconds = settings.countdown_seconds ?? 5
      const badSize = this.badSizes(settings.enabled_layouts)
      if (badSize) return json({ detail: badSize }, 422)
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
      const badSize = this.badSizes(body.enabled_layouts)
      if (badSize) return json({ detail: badSize }, 422)
      if (profile.is_active && body.enabled_layouts.length === 0) {
        return json({ detail: NO_SIZES }, 422)
      }
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
      settings.enabled_layouts = this.ordered(settings.enabled_layouts)
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
      if (profile.settings.enabled_layouts.length === 0) return json({ detail: NO_SIZES }, 409)
      if (this.validFrames(profile.settings.enabled_layouts) === 0) return json({ detail: NO_FRAMES }, 409)
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
