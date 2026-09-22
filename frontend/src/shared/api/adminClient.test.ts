import { describe, expect, it, vi } from 'vitest'

import {
  ADMIN_CSRF_HEADER,
  AdminApiError,
  createAdminApiClient,
  newProfileSettings,
  type SessionListener,
} from './adminClient'
import type { Fetcher } from './client'
import { defaultTheme } from '../../features/admin/testing/fakeAdminServer'
import { DEVICE_KEY_HEADER, type DeviceKeyStore } from './deviceKey'

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function keyStore(initial: string | null = 'k'.repeat(43)): DeviceKeyStore & { value: string | null } {
  const store = {
    value: initial,
    get: () => store.value,
    set: (key: string) => {
      store.value = key
    },
    clear: () => {
      store.value = null
    },
  }
  return store
}

const SESSION = { username: 'admin', csrf_token: 'c'.repeat(43), expires_in_seconds: 1800 }

type Mocked = { mock: { calls: Parameters<Fetcher>[] } }

function callOf(fetcher: Mocked, index: number): Parameters<Fetcher> {
  const call = fetcher.mock.calls[index]
  if (call === undefined) throw new Error(`no fetch call ${index}`)
  return call
}

function headersOf(call: Parameters<Fetcher>): Record<string, string> {
  return (call[1]?.headers ?? {}) as Record<string, string>
}

describe('createAdminApiClient', () => {
  it('logs in with the device key and sends the CSRF token on later mutations', async () => {
    const fetcher = vi.fn<Fetcher>(async (path) =>
      path === '/api/admin/auth/login' ? json(SESSION) : json({ id: 'p1' }, 201),
    )
    const api = createAdminApiClient(fetcher, keyStore())
    await api.login('admin', 'secret password')

    const [loginPath, loginInit] = fetcher.mock.calls[0] ?? []
    expect(loginPath).toBe('/api/admin/auth/login')
    expect(loginInit?.credentials).toBe('same-origin')
    expect(headersOf(callOf(fetcher, 0))[DEVICE_KEY_HEADER]).toBe('k'.repeat(43))
    expect(headersOf(callOf(fetcher, 0))[ADMIN_CSRF_HEADER]).toBeUndefined()

    await api.createProfile(newProfileSettings(defaultTheme(), ['strip_2x6']))
    const createHeaders = headersOf(callOf(fetcher, 1))
    expect(createHeaders[ADMIN_CSRF_HEADER]).toBe(SESSION.csrf_token)
    expect(createHeaders[DEVICE_KEY_HEADER]).toBe('k'.repeat(43))
    expect(JSON.parse(String(callOf(fetcher, 1)[1]?.body))).toMatchObject({
      countdown_seconds: 5,
      enabled_layouts: ['strip_2x6'],
      allow_surprise_me: false,
      theme: { source: 'preset', preset: 'midnight_blue' },
    })
  })

  it('never sends the device key or CSRF token on reads', async () => {
    const fetcher = vi.fn<Fetcher>(async () => json([]))
    const api = createAdminApiClient(fetcher, keyStore())
    await api.listProfiles(true)
    expect(callOf(fetcher, 0)[0]).toBe('/api/admin/profiles?include_deleted=true')
    expect(headersOf(callOf(fetcher, 0))[DEVICE_KEY_HEADER]).toBeUndefined()
  })

  it('refuses mutations without a paired device key', async () => {
    const fetcher = vi.fn<Fetcher>()
    const api = createAdminApiClient(fetcher, keyStore(null))
    await expect(api.login('admin', 'x')).rejects.toMatchObject({ kind: 'not-paired' })
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('reports an expired session after a 401 and forgets the CSRF token', async () => {
    let expired = false
    const fetcher = vi.fn<Fetcher>(async (path) => {
      if (path === '/api/admin/auth/login') return json(SESSION)
      return expired ? json({ detail: 'admin login required' }, 401) : json([])
    })
    const events: Parameters<SessionListener>[0][] = []
    const api = createAdminApiClient(fetcher, keyStore())
    api.onSessionChange((event) => events.push(event))
    await api.login('admin', 'pw')
    expired = true
    await expect(api.listProfiles()).rejects.toMatchObject({ kind: 'unauthenticated', status: 401 })
    expect(events).toEqual(['signed-in', 'expired'])
    expect(api.hasCsrfToken()).toBe(false)
  })

  it('treats device rejections as not paired and clears the stored key', async () => {
    const keys = keyStore()
    const fetcher = vi.fn<Fetcher>(async () => json({ detail: 'device key invalid' }, 403))
    const api = createAdminApiClient(fetcher, keys)
    await expect(api.activateProfile('p1')).rejects.toMatchObject({ kind: 'not-paired' })
    expect(keys.value).toBeNull()
  })

  it('does not report expiry for a wrong password', async () => {
    const events: string[] = []
    const fetcher = vi.fn<Fetcher>(async () => json({ detail: 'invalid username or password' }, 401))
    const api = createAdminApiClient(fetcher, keyStore())
    api.onSessionChange((event) => events.push(event))
    const error = await api.login('admin', 'wrong').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(AdminApiError)
    expect(error).toMatchObject({ kind: 'unauthenticated', messages: ['invalid username or password'] })
    expect(events).toEqual([])
  })

  it.each([
    [409, { detail: 'the profile was changed elsewhere' }, 'conflict'],
    [404, { detail: 'event profile not found: x' }, 'not-found'],
    [413, { detail: 'file is larger than 5 MB' }, 'too-large'],
    [503, { detail: 'another upload is in progress; try again' }, 'busy'],
  ] as const)('maps HTTP %s to %s', async (status, body, kind) => {
    const api = createAdminApiClient(async () => json(body, status), keyStore())
    await expect(api.getProfile('x')).rejects.toMatchObject({ kind, messages: [body.detail] })
  })

  it('splits server validation problems and FastAPI field errors into messages', async () => {
    const api = createAdminApiClient(
      async () => json({ detail: 'title must be 1-120 characters; unknown layouts: x' }, 422),
      keyStore(),
    )
    await expect(api.getProfile('x')).rejects.toMatchObject({
      kind: 'validation',
      messages: ['title must be 1-120 characters', 'unknown layouts: x'],
    })
    const pydantic = createAdminApiClient(
      async () => json({ detail: [{ loc: ['body', 'primary_color'], msg: 'bad colour' }] }, 422),
      keyStore(),
    )
    await expect(pydantic.getProfile('x')).rejects.toMatchObject({ messages: ['primary_color: bad colour'] })
  })

  it('exposes Retry-After for throttled logins', async () => {
    const api = createAdminApiClient(
      async () => json({ detail: 'too many failed logins' }, 429, { 'Retry-After': '120' }),
      keyStore(),
    )
    await expect(api.login('admin', 'x')).rejects.toMatchObject({ kind: 'throttled', retryAfterSeconds: 120 })
  })

  it('sends the revision with updates and deletes', async () => {
    const fetcher = vi.fn<Fetcher>(async () => json({ id: 'p1' }))
    const api = createAdminApiClient(fetcher, keyStore())
    await api.updateProfile('p1', newProfileSettings(defaultTheme(), []), 3)
    await api.deleteProfile('p1', 4)
    expect(callOf(fetcher, 0)[1]?.method).toBe('PUT')
    expect(JSON.parse(String(callOf(fetcher, 0)[1]?.body))).toMatchObject({ revision: 3 })
    expect(callOf(fetcher, 1)[0]).toBe('/api/admin/profiles/p1?revision=4')
    expect(callOf(fetcher, 1)[1]?.method).toBe('DELETE')
  })

  it('uploads assets as multipart without a manual Content-Type', async () => {
    const fetcher = vi.fn<Fetcher>(async () => json({ id: 'a1' }, 201))
    const api = createAdminApiClient(fetcher, keyStore())
    await api.uploadAsset('logo', new File([new Uint8Array([1, 2, 3])], 'logo.png', { type: 'image/png' }))
    const init = callOf(fetcher, 0)[1]
    expect(init?.body).toBeInstanceOf(FormData)
    expect((init?.body as FormData).get('kind')).toBe('logo')
    expect(headersOf(callOf(fetcher, 0))['Content-Type']).toBeUndefined()
    expect(api.assetContentUrl('a/1')).toBe('/api/admin/assets/a%2F1/content')
  })

  it('logout resolves only after the server confirms the session is gone', async () => {
    const events: string[] = []
    let mode: 'network' | 'server-error' | 'gone' = 'network'
    const fetcher = vi.fn<Fetcher>(async (path) => {
      if (path === '/api/admin/auth/login') return json(SESSION)
      if (mode === 'network') throw new TypeError('Failed to fetch')
      if (mode === 'server-error') return json({ detail: 'boom' }, 500)
      return json({ detail: 'admin login required' }, 401)
    })
    const api = createAdminApiClient(fetcher, keyStore())
    api.onSessionChange((event) => events.push(event))
    await api.login('admin', 'pw')

    await expect(api.logout()).rejects.toMatchObject({ kind: 'network' })
    mode = 'server-error'
    await expect(api.logout()).rejects.toMatchObject({ kind: 'server' })
    expect(events).toEqual(['signed-in'])
    expect(api.hasCsrfToken()).toBe(true)

    mode = 'gone' // already expired on the server: signing out is complete
    await api.logout()
    expect(events).toEqual(['signed-in', 'signed-out'])
  })

  it('logout retries once with a refreshed CSRF token after a 403', async () => {
    const fresh = { ...SESSION, csrf_token: 'f'.repeat(43) }
    const fetcher = vi.fn<Fetcher>(async (path, init) => {
      if (path === '/api/admin/auth/login') return json(SESSION)
      if (path === '/api/admin/auth/session') return json(fresh)
      const csrf = (init?.headers as Record<string, string>)[ADMIN_CSRF_HEADER]
      return csrf === fresh.csrf_token ? json(null, 204) : json({ detail: 'admin csrf token invalid' }, 403)
    })
    const api = createAdminApiClient(fetcher, keyStore())
    await api.login('admin', 'pw')
    await api.logout()
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      '/api/admin/auth/login',
      '/api/admin/auth/logout',
      '/api/admin/auth/session',
      '/api/admin/auth/logout',
    ])
    expect(api.hasCsrfToken()).toBe(false)
  })

  it('returns null from session() when signed out and reports network failures', async () => {
    const signedOut = createAdminApiClient(async () => json({ detail: 'admin login required' }, 401), keyStore())
    expect(await signedOut.session()).toBeNull()
    const offline = createAdminApiClient(async () => {
      throw new TypeError('Failed to fetch')
    }, keyStore())
    await expect(offline.listProfiles()).rejects.toMatchObject({ kind: 'network' })
  })
})

describe('frames', () => {
  it('uploads a frame with its layout and admin-chosen name', async () => {
    const fetcher = vi.fn<Fetcher>(async () => json({ id: 'f1', template_key: 'strip_2x6' }, 201))
    const api = createAdminApiClient(fetcher, keyStore())
    const file = new File([new Uint8Array([1, 2])], 'anything.png', { type: 'image/png' })
    await api.uploadFrame('strip_2x6', 'Gold border', file)
    const [path, init] = callOf(fetcher, 0)
    expect(path).toBe('/api/admin/frames')
    const form = init?.body as FormData
    expect(form.get('template_key')).toBe('strip_2x6')
    expect(form.get('name')).toBe('Gold border')
    expect(form.get('file')).toBeInstanceOf(File)
    expect(headersOf(callOf(fetcher, 0))['Content-Type']).toBeUndefined()
  })

  it('lists, replaces, renames and deletes frames', async () => {
    const fetcher = vi.fn<Fetcher>(async (_path, init) =>
      init?.method === 'DELETE' ? json(null, 204) : json([]),
    )
    const api = createAdminApiClient(fetcher, keyStore())
    await api.listFrames()
    await api.listFrames('print_3x4')
    await api.replaceFrameFile('f1', new File([new Uint8Array([3])], 'x.png', { type: 'image/png' }))
    await api.renameFrame('f1', 'New name')
    await api.deleteFrame('f1')
    expect(fetcher.mock.calls.map((call) => `${call[1]?.method ?? 'GET'} ${call[0]}`)).toEqual([
      'GET /api/admin/frames',
      'GET /api/admin/frames?template_key=print_3x4',
      'POST /api/admin/frames/f1/replace',
      'PUT /api/admin/frames/f1/name',
      'DELETE /api/admin/frames/f1',
    ])
    expect(JSON.parse(String(callOf(fetcher, 3)[1]?.body))).toEqual({ name: 'New name' })
  })

  it('reports that a frame in use can not be deleted', async () => {
    const api = createAdminApiClient(
      async () => json({ detail: 'this frame is still used by: Wedding' }, 409),
      keyStore(),
    )
    await expect(api.deleteFrame('f1')).rejects.toMatchObject({
      kind: 'conflict',
      messages: ['this frame is still used by: Wedding'],
    })
  })

  it('reads the theme catalogue and asks the server to extract a theme', async () => {
    const fetcher = vi.fn<Fetcher>(async () => json({ tokens: {}, palette: [] }))
    const api = createAdminApiClient(fetcher, keyStore())
    await api.themeCatalog()
    await api.extractTheme('asset-1')
    expect(callOf(fetcher, 0)[0]).toBe('/api/admin/themes')
    expect(callOf(fetcher, 1)[0]).toBe('/api/admin/themes/extract')
    expect(callOf(fetcher, 1)[1]?.method).toBe('POST')
    expect(JSON.parse(String(callOf(fetcher, 1)[1]?.body))).toEqual({ background_asset_id: 'asset-1' })
  })

  it('builds same-origin URLs for the frame file, its preview and the template downloads', () => {
    const api = createAdminApiClient(async () => json({}), keyStore())
    expect(api.frameContentUrl('f 1')).toBe('/api/admin/frames/f%201/content')
    expect(api.framePreviewUrl('f1')).toBe('/api/admin/frames/f1/preview/1.jpg')
    expect(api.framePreviewUrl('f1', 2)).toBe('/api/admin/frames/f1/preview/2.jpg')
    // A replaced file has a new sha256, hence a new URL the browser has never cached.
    expect(api.frameContentUrl('f1', 'abc')).toBe('/api/admin/frames/f1/content?v=abc')
    expect(api.framePreviewUrl('f1', 1, 'abc')).toBe('/api/admin/frames/f1/preview/1.jpg?v=abc')
    expect(api.templateGuideUrl('strip_2x6')).toBe('/api/templates/strip_2x6/guide.png')
    expect(api.templateBlankUrl('strip_2x6')).toBe('/api/templates/strip_2x6/blank.png')
  })
})