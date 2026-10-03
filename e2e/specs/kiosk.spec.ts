import { expect, test, type Page } from './support/fixtures'

import { PERSISTED, pairAndSignIn, profileRow } from './support/admin'

/**
 * Phase 12: the booth as an unattended kiosk. A lost server is said plainly and waited out, a
 * double tap acts once, a long press or drag does nothing, a camera that comes back carries on,
 * and the organizer can see what the machine runs. Fullscreen itself, a real touch screen and a
 * real USB camera are checked by hand on the booth machine.
 */

test.describe.configure({ mode: 'serial' })

/** Prepared by capture.spec: one second per photo, every size offered. */
const QUICK = 'E2E Capture'

async function activate(page: Page, name: string): Promise<void> {
  await page.goto('/admin')
  const row = profileRow(page, name)
  const button = row.getByRole('button', { name: `Activate ${name}`, exact: true })
  if (await button.isEnabled()) await button.click()
  await expect(row.getByText('Active', { exact: true })).toBeVisible()
}

async function chooseFrame(page: Page): Promise<void> {
  await page.getByRole('tab', { name: '3×4' }).click()
  const slide = page.getByTestId('frame-slide').filter({ hasText: 'Midnight' }).first()
  await slide.scrollIntoViewIfNeeded()
  await slide.getByRole('button', { name: 'Use this frame' }).click()
  await page
    .getByRole('dialog', { name: 'Use this frame?' })
    .getByRole('button', { name: 'Start with this frame' })
    .click()
  await expect(page).toHaveURL(/\/booth\/capture$/)
}

/** The booth's own calls to one step of the visit, counted as the browser sends them. */
function counter(page: Page, step: string): () => number {
  let calls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith(`/${step}`)) calls += 1
  })
  return () => calls
}

test('the booth to test with is the quick one', async ({ page }) => {
  await pairAndSignIn(page)
  await activate(page, QUICK)
})

test('a lost server is shown as reconnecting, and the booth carries on when it is back', async ({
  page,
}) => {
  await pairAndSignIn(page)
  await page.goto('/booth')
  await expect(page.getByTestId('booth-shell')).toBeVisible()
  await expect(page.getByTestId('booth-offline')).toHaveCount(0)

  // The server stops answering (as when it is restarted or the machine is busy).
  test.setTimeout(120_000)
  await page.route('**/api/health', (route) => route.abort('connectionrefused'))
  await expect(page.getByTestId('booth-offline')).toContainText('The booth is reconnecting', {
    timeout: 20_000,
  })
  // Nothing under the cover takes input, not even a key on a focused button (P12-R5).
  await expect(page.getByTestId('booth-screen')).toHaveAttribute('inert', '')
  await expect(page.getByTestId('booth-offline')).toBeFocused()

  await page.unroute('**/api/health')
  await expect(page.getByTestId('booth-offline')).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByTestId('booth-screen')).not.toHaveAttribute('inert')

  // A proxy in front of a stopped server answers instead of the server: that is lost too.
  await page.route('**/api/health', (route) => route.fulfill({ status: 502, body: 'Bad Gateway' }))
  await expect(page.getByTestId('booth-offline')).toBeVisible({ timeout: 20_000 })
  await page.unroute('**/api/health')
  await expect(page.getByTestId('booth-offline')).toHaveCount(0, { timeout: 15_000 })

  // A server that takes the request and never answers is lost too (P12-R2).
  await page.route('**/api/health', () => undefined)
  await expect(page.getByTestId('booth-offline')).toBeVisible({ timeout: 25_000 })
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await expect(page.getByTestId('booth-offline')).toHaveCount(0, { timeout: 15_000 })
})
test('a long press and a drag do nothing, and the booth asks for the whole screen', async ({
  page,
}) => {
  await pairAndSignIn(page)
  await page.goto('/booth')
  await expect(page.getByTestId('booth-shell')).toBeVisible()

  const refused = await page.evaluate(() => {
    const menu = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    const drag = new Event('dragstart', { bubbles: true, cancelable: true })
    document.body.dispatchEvent(menu)
    document.body.dispatchEvent(drag)
    return { menu: menu.defaultPrevented, drag: drag.defaultPrevented }
  })
  expect(refused).toEqual({ menu: true, drag: true })
  const viewport = await page.locator('meta[name="viewport"]').getAttribute('content')
  expect(viewport).toContain('user-scalable=no')

  // The support fixtures count the request instead of honouring it (see support/fixtures.ts).
  await page.getByTestId('booth-shell').click()
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { pbFullscreenAsked: number }).pbFullscreenAsked))
    .toBeGreaterThan(0)

  // Admin is not a kiosk: a long press works there as usual.
  await page.goto('/admin')
  const admin = await page.evaluate(() => {
    const menu = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    document.body.dispatchEvent(menu)
    return menu.defaultPrevented
  })
  expect(admin).toBe(false)
})

test('a double tap on each booth button acts once', async ({ page }) => {
  test.setTimeout(120_000)
  await pairAndSignIn(page)
  const finishes = counter(page, 'finish')
  const renders = counter(page, 'render')
  await page.goto('/booth/frames')
  await chooseFrame(page)
  await expect(page.getByRole('heading', { name: 'All photos taken' })).toBeVisible({
    timeout: 60_000,
  })

  await page.getByRole('button', { name: 'These are good' }).dblclick()
  await expect(page).toHaveURL(/\/booth\/decorate$/)
  expect(finishes()).toBe(1)

  await page.getByRole('button', { name: 'Finish' }).click()
  await page
    .getByRole('dialog', { name: 'Finish your photos?' })
    .getByRole('button', { name: 'Make my photos' })
    .dblclick()
  await expect(page).toHaveURL(/\/booth\/done$/, { timeout: 30_000 })
  await expect(page.getByTestId('delivery-qr')).toBeVisible({ timeout: 30_000 })
  expect(renders()).toBe(1)

  await page.getByRole('button', { name: 'Done' }).dblclick()
  await expect(page).toHaveURL(/\/booth$/)
  expect(await (await page.request.get('/api/booth/sessions/current')).json()).toBeNull()
})

test('a camera unplugged and plugged back in carries on with the same visit', async ({ page }) => {
  test.setTimeout(120_000)
  await pairAndSignIn(page)
  await page.addInitScript(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 640
    canvas.height = 480
    let stream: MediaStream | null = null
    let plugged = true
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () =>
          plugged ? [{ kind: 'videoinput', deviceId: 'fake', label: 'Fake' }] : [],
        getUserMedia: async () => {
          if (!plugged) {
            const error = new Error('no camera')
            error.name = 'NotFoundError'
            throw error
          }
          const context = canvas.getContext('2d')
          if (context) {
            context.fillStyle = '#884422'
            context.fillRect(0, 0, canvas.width, canvas.height)
          }
          stream = canvas.captureStream(10)
          return stream
        },
      },
    })
    const control = window as unknown as { pbUnplug: () => void; pbPlugIn: () => void }
    control.pbUnplug = () => {
      plugged = false
      for (const track of stream?.getTracks() ?? []) track.stop()
    }
    control.pbPlugIn = () => {
      plugged = true
    }
  })
  await page.goto('/booth/frames')
  await chooseFrame(page)
  await expect
    .poll(async () => (await (await page.request.get('/api/booth/sessions/current')).json())?.taken, {
      timeout: 30_000,
    })
    .toBe(1)
  const before = await (await page.request.get('/api/booth/sessions/current')).json()

  await page.evaluate(() => (window as unknown as { pbUnplug: () => void }).pbUnplug())
  await expect(page.getByRole('alert')).toContainText('The camera was disconnected', {
    timeout: 20_000,
  })

  // Still unplugged: trying again says so instead of pretending.
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('alert')).toContainText('No camera is connected to this booth')

  await page.evaluate(() => (window as unknown as { pbPlugIn: () => void }).pbPlugIn())
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('heading', { name: 'All photos taken' })).toBeVisible({
    timeout: 30_000,
  })
  const after = await (await page.request.get('/api/booth/sessions/current')).json()
  expect(after.id).toBe(before.id) // the same visit, not a new one
  expect(after.taken).toBe(2)
  await page.getByRole('button', { name: 'These are good' }).click()
})

test('the start page says which version runs and leads to the booth and Admin', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/')
  await expect(page.getByTestId('version')).toContainText(/Version \S+ · API \d+ · dummy/)
  await expect(page.getByTestId('version')).toContainText('database 0011_retention')
  await expect(page.getByRole('link', { name: 'Admin' })).toBeVisible()
  await page.getByRole('link', { name: 'Open the booth' }).click()
  await expect(page).toHaveURL(/\/booth$/)
  await expect(page.getByTestId('booth-shell')).toBeVisible()
})

test('the System page tells the organizer how the booth is', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/system')
  await expect(page.getByRole('heading', { name: 'System' })).toBeVisible()
  const health = page.getByRole('region', { name: 'Health' })
  await expect(health.getByText('Database', { exact: true })).toBeVisible()
  await expect(health.getByText('OK', { exact: true })).toBeVisible()
  await expect(health.getByText(QUICK, { exact: true })).toBeVisible()
  await expect(health.getByText(/ GB of [\d.]+ GB/)).toBeVisible()
  const addresses = page.getByRole('region', { name: 'Addresses' })
  // The booth address is where the screens really are: here the e2e UI on its own port (P12-R7).
  const boothAddress = addresses.getByText(/^http:\/\/127\.0\.0\.1:\d+\/booth$/)
  await expect(boothAddress).toHaveText('http://127.0.0.1:5192/booth')
  const version = page.getByRole('region', { name: 'Version' })
  await expect(version.getByText('0011_retention')).toBeVisible()
  await page.getByRole('button', { name: 'Check again' }).click()
  await expect(health.getByText('OK', { exact: true })).toBeVisible()
  await page.goto((await boothAddress.textContent()) ?? '')
  await expect(page.getByTestId('booth-shell')).toBeVisible()
})

test('the event the later specs expect is active again', async ({ page }) => {
  await pairAndSignIn(page)
  await activate(page, PERSISTED.copy)
})
