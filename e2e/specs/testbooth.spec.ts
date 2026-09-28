import { expect, test, type Page } from '@playwright/test'

import { pairAndSignIn, profileRow } from './support/admin'

/**
 * Admin → "Test booth": the organizer runs the booth's own screens, with this machine's own
 * camera, against a saved event.
 *
 * What is proven here is what an organizer is promised: the menu item is always there, the event
 * picked is only tried (never activated, never changed), the photos taken are the real camera's,
 * each one appears under its own number and can be looked at large, and leaving the test takes
 * the test's data with it while a guest's visit elsewhere is left alone.
 */

test.describe.configure({ mode: 'serial' })

/** The event prepared by capture.spec: one second per photo, and not the live one. */
const TRIED = 'E2E Capture'
/** Shape-valid but nobody's: the gate must refuse before it ever looks a profile up. */
const SOME_PROFILE = '00000000-0000-4000-8000-000000000000'

interface Profile {
  id: string
  revision: number
  is_active: boolean
  settings: { name: string } & Record<string, unknown>
}

async function profiles(page: Page): Promise<Profile[]> {
  const response = await page.request.get('/api/admin/profiles')
  expect(response.status()).toBe(200)
  return (await response.json()) as Profile[]
}

async function visit(page: Page): Promise<{ id: string; is_test: boolean; taken: number } | null> {
  const response = await page.request.get('/api/booth/sessions/current')
  return (await response.json()) as never
}

async function openTestBooth(page: Page): Promise<void> {
  await page.goto('/admin')
  await page.getByRole('link', { name: 'Test booth' }).click()
  await expect(page).toHaveURL(/\/admin\/test$/)
  await expect(page.getByRole('heading', { name: 'Test booth' })).toBeVisible()
}

/** Start a test on that event and walk the booth's own screens to the photos. */
async function runTest(page: Page, eventName: string, frame = 'Midnight'): Promise<void> {
  await page.getByLabel('Event to try').selectOption({ label: eventName })
  await page.getByRole('button', { name: 'Start booth test' }).click()
  await expect(page.getByTestId('test-banner')).toContainText('TEST')
  const booth = page.getByTestId('booth-shell')
  // The booth's own start screen, with this event's own Start text.
  await booth.getByTestId('start-screen').getByRole('button').click()
  const slide = booth.getByTestId('frame-slide').filter({ hasText: frame }).first()
  await slide.scrollIntoViewIfNeeded()
  await slide.getByRole('button', { name: 'Use this frame' }).click()
  await page
    .getByRole('dialog', { name: 'Use this frame?' })
    .getByRole('button', { name: 'Start with this frame' })
    .click()
  await expect(booth.getByLabel('Camera preview')).toBeVisible()
}

test('"Test booth" is always in the Admin menu, and needs an admin session', async ({
  page,
  browser,
}) => {
  const stranger = await browser.newContext()
  try {
    const other = await stranger.newPage()
    // Not paired and not signed in: the test-booth routes say no before anything is read.
    const menu = await other.request.get(`/api/admin/booth-test/menu/${SOME_PROFILE}`)
    expect([401, 403]).toContain(menu.status())
    const cleanup = await other.request.post('/api/admin/booth-test/cleanup')
    expect([401, 403]).toContain(cleanup.status())
  } finally {
    await stranger.close()
  }

  await pairAndSignIn(page)
  await openTestBooth(page)
  // The drawn camera of the automated tests is nowhere in the organizer's booth.
  await expect(page.getByLabel('Camera')).toBeVisible()
  await expect(page.getByRole('option', { name: /Test camera/ })).toHaveCount(0)
})

test('trying a saved event takes real photos and leaves the event exactly as it was', async ({
  page,
}) => {
  await pairAndSignIn(page)
  const before = await profiles(page)
  const tried = before.find((profile) => profile.settings.name === TRIED)
  expect(tried, `${TRIED} is prepared by capture.spec`).toBeTruthy()
  expect(tried?.is_active).toBe(false)
  const wasActive = before.find((profile) => profile.is_active)?.id

  await openTestBooth(page)
  await runTest(page, TRIED)

  // The visit is the server's, marked as a test, and its photos come from getUserMedia.
  await expect.poll(async () => (await visit(page))?.taken ?? 0, { timeout: 30_000 }).toBe(2)
  const running = await visit(page)
  expect(running?.is_test).toBe(true)

  const booth = page.getByTestId('booth-shell')
  await expect(booth.getByRole('heading', { name: 'All photos taken' })).toBeVisible()
  await expect(booth.getByTestId('captured-photo')).toHaveCount(2)
  await expect(booth.getByRole('img', { name: 'Photo 1' }).first()).toBeVisible()
  await expect(booth.getByRole('img', { name: 'Photo 2' })).toBeVisible()
  await expect(booth.getByText('Midnight · 3×4 · 2 photos')).toBeVisible()

  // Nothing about the event moved: it was read, not written, and never activated.
  const after = await profiles(page)
  expect(after.find((profile) => profile.is_active)?.id).toBe(wasActive)
  const same = after.find((profile) => profile.id === tried?.id)
  expect(same?.revision).toBe(tried?.revision)
  expect(same?.settings).toEqual(tried?.settings)
})

test('each photo is shown under its own number and opens large without touching the camera', async ({
  page,
}) => {
  await pairAndSignIn(page)
  await openTestBooth(page)
  await runTest(page, TRIED)
  await expect.poll(async () => (await visit(page))?.taken ?? 0, { timeout: 30_000 }).toBe(2)

  const booth = page.getByTestId('booth-shell')
  const slots = booth.getByTestId('captured-photo')
  await expect(slots.nth(0)).toContainText('Photo 1')
  await expect(slots.nth(1)).toContainText('Photo 2')
  const first = await slots.nth(0).getByRole('img').getAttribute('src')
  const second = await slots.nth(1).getByRole('img').getAttribute('src')
  expect(first).not.toBe(second) // two shots, two photos, never the same picture twice

  // The review shows a stored photo, not the camera, and pressing a place changes which one.
  await expect(booth.getByLabel('Camera preview')).toHaveCount(0)
  await expect(booth.getByTestId('review-photo')).toHaveAttribute('src', String(first))
  await booth.getByRole('button', { name: 'Show photo 2' }).click()
  await expect(booth.getByTestId('review-photo')).toHaveAttribute('src', String(second))

  await booth.getByRole('button', { name: 'Photo 2, see it bigger' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Photo 2' })).toBeVisible()
  await expect(dialog.getByTestId('photo-large')).toHaveAttribute('src', String(second))
  // Looking at a photo opens no camera at all on the review screen.
  await expect(booth.getByLabel('Camera preview')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('Admin steps aside while the test runs and comes back when it is left', async ({ page }) => {
  await pairAndSignIn(page)
  await openTestBooth(page)
  // Setting the test up is an ordinary Admin page.
  await expect(page.getByRole('navigation')).toBeVisible()
  await expect(page.getByText('Signed in as admin')).toBeVisible()
  await expect(page.getByTestId('dummy-badge')).toBeVisible()

  await runTest(page, TRIED)
  // Running it, the booth is the whole display: no header, no navigation, no badge, no scrolling.
  await expect(page.getByRole('navigation')).toHaveCount(0)
  await expect(page.getByText('Signed in as admin')).toHaveCount(0)
  await expect(page.getByTestId('dummy-badge')).toHaveCount(0)
  await expect(page.locator('html')).toHaveAttribute('data-booth-immersive', '')
  const shell = (await page.getByTestId('booth-shell').boundingBox()) as {
    width: number
    height: number
  }
  const view = page.viewportSize() as { width: number; height: number }
  expect(Math.round(shell.width)).toBe(view.width)
  expect(Math.round(shell.height)).toBe(view.height)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    view.width,
  )
  // Only the mark and the way out stay on top of it.
  await expect(page.getByTestId('test-banner')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Exit test' })).toBeVisible()

  await page.getByRole('button', { name: 'Exit test' }).click()
  await expect(page.getByRole('button', { name: 'Start booth test' })).toBeVisible()
  await expect(page.getByRole('navigation')).toBeVisible()
  await expect(page.getByTestId('dummy-badge')).toBeVisible()
  await expect(page.locator('html')).not.toHaveAttribute('data-booth-immersive', '')
})

test('the organizer test and the guest booth are one and the same screen', async ({ page }) => {
  await pairAndSignIn(page)
  // A guest's booth: the same shell, with no Admin chrome anywhere near it.
  await page.goto('/booth')
  await expect(page.getByTestId('booth-shell')).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-booth-immersive', '')
  await expect(page.getByRole('navigation')).toHaveCount(0)
  const guest = (await page.getByTestId('booth-shell').boundingBox()) as { width: number }
  const view = page.viewportSize() as { width: number }
  expect(Math.round(guest.width)).toBe(view.width)

  // And leaving the booth address gives the app back.
  await page.goto('/admin')
  await expect(page.locator('html')).not.toHaveAttribute('data-booth-immersive', '')
  await expect(page.getByTestId('dummy-badge')).toBeVisible()
})

test('leaving the test takes its data with it, however often it is run', async ({ page }) => {
  test.setTimeout(120_000) // two full test visits, one after the other
  await pairAndSignIn(page)

  for (const round of [1, 2]) {
    await openTestBooth(page)
    await runTest(page, TRIED)
    await expect.poll(async () => (await visit(page))?.taken ?? 0, { timeout: 30_000 }).toBe(2)
    const testVisit = await visit(page)
    expect(testVisit?.is_test, `round ${round}`).toBe(true)

    await page.getByRole('button', { name: 'Exit test' }).click()
    await expect(page.getByRole('button', { name: 'Start booth test' })).toBeVisible()
    // The test visit and its photos are gone, and this device is back to no visit at all.
    await expect
      .poll(async () => (await page.request.get(`/api/booth/sessions/${testVisit?.id}`)).status())
      .toBe(404)
    expect(await visit(page)).toBeNull()
  }

  // The live event is still the live one: testing changed nothing.
  await page.goto('/admin')
  await expect(profileRow(page, TRIED).getByText('Active', { exact: true })).toHaveCount(0)
})

test('clearing away a test never touches a guest booth', async ({ page, browser }) => {
  test.setTimeout(120_000) // a guest's visit beside the organizer's test
  await pairAndSignIn(page)

  // A guest's booth, on its own device, taking its own photos.
  const guestContext = await browser.newContext()
  try {
    const guest = await guestContext.newPage()
    await pairAndSignIn(guest)
    await guest.goto('/booth/frames')
    const slide = guest.getByTestId('frame-slide').filter({ hasText: 'Midnight' }).first()
    await slide.scrollIntoViewIfNeeded()
    await slide.getByRole('button', { name: 'Use this frame' }).click()
    await guest
      .getByRole('dialog', { name: 'Use this frame?' })
      .getByRole('button', { name: 'Start with this frame' })
      .click()
    await expect(guest).toHaveURL(/\/booth\/capture$/)
    const guestVisit = await visit(guest)
    expect(guestVisit?.is_test).toBe(false)
    await expect.poll(async () => (await visit(guest))?.taken ?? 0, { timeout: 45_000 }).toBe(2)

    // The organizer tests and leaves: the cleanup runs on opening the page and on leaving it.
    await openTestBooth(page)
    await runTest(page, TRIED)
    await expect.poll(async () => (await visit(page))?.taken ?? 0, { timeout: 30_000 }).toBe(2)
    await page.getByRole('button', { name: 'Exit test' }).click()
    await expect(page.getByRole('button', { name: 'Start booth test' })).toBeVisible()

    // The guest's visit and its photos were never the cleanup's business.
    const stillThere = await guest.request.get(`/api/booth/sessions/${guestVisit?.id}`)
    expect(stillThere.status()).toBe(200)
    const kept = (await stillThere.json()) as { is_test: boolean; taken: number }
    expect(kept.is_test).toBe(false)
    expect(kept.taken).toBe(2) // its photos are still there too
    await guest.getByRole('button', { name: 'These are good' }).click()
  } finally {
    await guestContext.close()
  }
})
