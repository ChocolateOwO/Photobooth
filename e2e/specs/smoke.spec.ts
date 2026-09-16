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

  const paired = await page.request.post('/api/booth/ping')
  expect(paired.status()).toBe(200)
  expect(await paired.json()).toEqual({ ok: true })

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
