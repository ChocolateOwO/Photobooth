import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { expect, request, test } from '@playwright/test'

const instanceRoot = process.env.PHOTOBOOTH_E2E_INSTANCE_ROOT ?? ''

function runtimeSecret(name: string): string {
  return readFileSync(join(instanceRoot, 'config', 'runtime', name), 'utf-8')
}

async function freshPairingCode(baseURL: string): Promise<string> {
  const api = await request.newContext({
    baseURL,
    extraHTTPHeaders: { 'X-Photobooth-Launcher': runtimeSecret('launcher.token') },
  })
  try {
    // Rotation is rate limited to 1/s; retry briefly if a previous test just rotated.
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const response = await api.post('/kiosk/pairing-code/rotate')
      if (response.status() === 204) {
        return runtimeSecret('pairing.code')
      }
      expect(response.status()).toBe(429)
      await new Promise((resolve) => setTimeout(resolve, 1100))
    }
  } finally {
    await api.dispose()
  }
  throw new Error('could not rotate pairing code')
}

test('shell loads with DUMMY badge and API OK, then pairs the kiosk', async ({ page, baseURL }) => {
  expect(instanceRoot).not.toBe('')
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Photobooth' })).toBeVisible()
  await expect(page.getByTestId('dummy-badge')).toBeVisible()
  await expect(page.getByTestId('dummy-badge')).toHaveText('DUMMY')
  await expect(page.getByTestId('health-status')).toHaveText('API OK')
  await expect(page.getByTestId('pairing-status')).toContainText('Kiosk not paired')

  const unpaired = await page.request.post('/api/booth/ping')
  expect(unpaired.status()).toBe(401)

  const code = await freshPairingCode(baseURL ?? '')
  await page.goto(`/kiosk/pair?code=${encodeURIComponent(code)}`)
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByTestId('pairing-status')).toHaveText('Kiosk paired')
  await expect(page.getByTestId('dummy-badge')).toBeVisible()

  // A real browser mutation from the Dummy UI origin: Origin header + CSRF token from same-origin read.
  const paired = await page.evaluate(async () => {
    const status = (await (await fetch('/api/kiosk/status')).json()) as { csrf_token: string }
    const response = await fetch('/api/booth/ping', {
      method: 'POST',
      headers: { 'X-Photobooth-CSRF': status.csrf_token },
    })
    return { status: response.status, body: (await response.json()) as unknown }
  })
  expect(paired).toEqual({ status: 200, body: { ok: true } })

  // The cookie alone (no Origin / CSRF, e.g. a non-browser client) is refused.
  const cookieOnly = await page.request.post('/api/booth/ping')
  expect(cookieOnly.status()).toBe(403)

  // Another local application on a different port is same-site: the Strict cookie IS sent with a
  // cross-origin form POST, so the server must reject it by Origin/CSRF.
  await page.route('http://127.0.0.1:5193/attack', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: `<form id="f" method="POST" action="http://127.0.0.1:5192/api/booth/ping"></form>
             <script>document.getElementById('f').submit()</script>`,
    }),
  )
  const attackResponse = page.waitForResponse(
    (response) => response.url() === 'http://127.0.0.1:5192/api/booth/ping',
  )
  await page.goto('http://127.0.0.1:5193/attack')
  const attack = await attackResponse
  expect((await attack.request().allHeaders())['cookie']).toContain('pb_device_dummy=')
  expect(attack.status()).toBe(403)

  await page.goto('/')
  const reused = await page.request.get(`/kiosk/pair?code=${encodeURIComponent(code)}`, {
    maxRedirects: 0,
  })
  expect(reused.status()).toBe(403)
})

test('a browser without the device cookie cannot mutate booth state', async ({ browser }) => {
  const context = await browser.newContext({ baseURL: 'http://127.0.0.1:5192' })
  try {
    const response = await context.request.post('/api/booth/ping')
    expect(response.status()).toBe(401)
    const rotate = await context.request.post('/kiosk/pairing-code/rotate')
    expect(rotate.status()).toBe(401)
  } finally {
    await context.close()
  }
})

test('large touch target on the status panel', async ({ page }) => {
  await page.goto('/')
  const box = await page.getByRole('button', { name: 'Check again' }).boundingBox()
  expect(box).not.toBeNull()
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(64)
})

test('delivery listener exposes nothing but its own routes', async () => {
  const api = await request.newContext({ baseURL: 'http://127.0.0.1:8114' })
  try {
    expect((await api.get('/d/_alive')).status()).toBe(200)
    expect((await api.get('/api/health')).status()).toBe(404)
    expect((await api.post('/api/booth/ping')).status()).toBe(404)
  } finally {
    await api.dispose()
  }
})
