import { expect, test, type Page } from '@playwright/test'

import { PERSISTED, pairAndSignIn, profileRow } from './support/admin'

/**
 * The photo session: from the confirmed frame to a full set of photos.
 *
 * There is only one camera in the booth: the machine's own, through `getUserMedia`. These runs
 * point that same code path at Chromium's fake capture device (see the Playwright config), so no
 * webcam is needed and the picture still moves. The refusals are exercised too: a blocked camera,
 * a missing one and one unplugged mid-session.
 */

test.describe.configure({ mode: 'serial' })

const PROFILE = 'E2E Capture'
/** `slot` is what the template keeps of one photo: the shape the booth frames the guest in. */
const LAYOUTS = [
  { pill: '3×4', key: 'print_3x4', photos: 2, slot: { width: 810, height: 540 } },
  { pill: '4×6', key: 'print_4x6', photos: 4, slot: { width: 555, height: 740 } },
  { pill: '2×6', key: 'strip_2x6', photos: 6, slot: { width: 540, height: 405 } },
] as const

/**
 * The picture on screen has the slot's shape, is as large as the screen allows, and nothing is
 * stretched. A few pixels of rounding are allowed; a wrong shape is not.
 */
async function expectSlotShape(page: Page, slot: { width: number; height: number }): Promise<void> {
  const frame = page.getByTestId('photo-frame')
  const box = (await frame.boundingBox()) as { width: number; height: number }
  expect(box.width).toBeGreaterThan(80)
  expect(box.height).toBeGreaterThan(80)
  expect(box.width / box.height).toBeCloseTo(slot.width / slot.height, 1)
  // It fills the room it is given in at least one direction.
  const stage = (await page.getByTestId('photo-frame').evaluate((node) => {
    const parent = node.parentElement as HTMLElement
    const rect = parent.getBoundingClientRect()
    return { width: rect.width, height: rect.height }
  })) as { width: number; height: number }
  const fills = box.width >= stage.width - 2 || box.height >= stage.height - 2
  expect(fills, `${box.width}x${box.height} inside ${stage.width}x${stage.height}`).toBe(true)
}

function sizePill(page: Page, label: string) {
  return page
    .getByRole('group', { name: 'Photo sizes available' })
    .getByRole('button', { name: new RegExp(`^${label}`) })
}

/** The booth exactly as a guest opens it: a plain address, and the machine's own camera. */
async function openBooth(page: Page, path = '/booth/frames'): Promise<void> {
  await page.goto(path)
}

async function chooseFrame(page: Page, label: string): Promise<void> {
  const slide = page.getByTestId('frame-slide').filter({ hasText: label }).first()
  await slide.scrollIntoViewIfNeeded()
  await slide.getByRole('button', { name: 'Use this frame' }).click()
  await page
    .getByRole('dialog', { name: 'Use this frame?' })
    .getByRole('button', { name: 'Start with this frame' })
    .click()
  await expect(page).toHaveURL(/\/booth\/capture$/)
}

/** The visit as the server sees it (the booth's own API, with this browser's device cookie). */
async function visit(page: Page): Promise<{
  id: string
  state: string
  taken: number
  expected_captures: number
  shots: { shot_index: number; attempt_no: number; done: boolean }[]
}> {
  const response = await page.request.get('/api/booth/sessions/current')
  return (await response.json()) as never
}

async function waitForPhotos(page: Page, taken: number, timeout = 60_000): Promise<void> {
  await expect
    .poll(async () => (await visit(page))?.taken ?? 0, { timeout, intervals: [400] })
    .toBe(taken)
}

const RETAKE_LABELS = {
  none: 'No retakes',
  per_photo: 'Retake any single photo',
  all: 'Retake all photos',
} as const

/** The organizer changes the event the way an organizer does: in the profile editor. */
async function settings(
  page: Page,
  changes: {
    countdown?: number
    mirror?: boolean
    retake?: keyof typeof RETAKE_LABELS
    inactivity?: number
  },
): Promise<void> {
  await page.goto('/admin')
  await profileRow(page, PROFILE).getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Edit Event Profile' })).toBeVisible()
  if (changes.countdown !== undefined) {
    await page
      .getByRole('spinbutton', { name: 'Countdown before each photo' })
      .fill(String(changes.countdown))
  }
  if (changes.mirror !== undefined) {
    const mirror = page.getByRole('checkbox', { name: 'Mirror the camera preview' })
    if (changes.mirror) await mirror.check()
    else await mirror.uncheck()
  }
  if (changes.retake !== undefined) {
    await page.getByRole('radio', { name: RETAKE_LABELS[changes.retake] }).check()
  }
  if (changes.inactivity !== undefined) {
    await page.getByLabel('Inactivity timeout (seconds)').fill(String(changes.inactivity))
  }
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toBeVisible()
  await page.getByRole('button', { name: 'Close' }).click()
}

test('the organizer prepares an event whose photos can be taken quickly', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: 'New profile' }).click()
  await page.getByLabel('Profile name').fill(PROFILE)
  await page.getByLabel('Title', { exact: true }).fill('Say cheese')
  // One second per photo keeps the runs short; 1 to 10 is what the profile allows.
  await page.getByRole('spinbutton', { name: 'Countdown before each photo' }).fill('1')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toBeVisible()
  await page.getByRole('button', { name: 'Close' }).click()
  await page.getByRole('link', { name: 'Back to profiles' }).click()
  await profileRow(page, PROFILE).getByRole('button', { name: `Activate ${PROFILE}` }).click()
  await expect(profileRow(page, PROFILE).getByText('Active', { exact: true })).toBeVisible()
})

for (const layout of LAYOUTS) {
  test(`a ${layout.pill} session takes exactly ${layout.photos} photos, one per shot`, async ({
    page,
  }) => {
    await pairAndSignIn(page)
    await openBooth(page)
    await page.getByRole('tab', { name: layout.pill }).click()
    await chooseFrame(page, 'Midnight')

    // The countdown itself is watched where it is slow enough to see (its own test below).
    const progress = page.getByTestId('capture-progress')
    await expect(progress).toHaveText(new RegExp(`Photo \\d of ${layout.photos}`))

    // The guest sees themselves in the shape this size keeps, as big as the screen allows, and
    // the booth owns the whole display with no picker of its own on it.
    await expect(page.getByTestId('booth-shell')).toBeVisible()
    await expect(page.getByLabel('Camera preview')).toBeVisible()
    await expectSlotShape(page, layout.slot)
    await expect(page.getByLabel('Camera', { exact: true })).toHaveCount(0)

    await waitForPhotos(page, layout.photos)

    const finished = await visit(page)
    expect(finished.expected_captures).toBe(layout.photos)
    expect(finished.shots.filter((shot) => shot.done)).toHaveLength(layout.photos)
    expect(new Set(finished.shots.map((shot) => shot.shot_index)).size).toBe(layout.photos)
    await expect(page.getByRole('heading', { name: 'All photos taken' })).toBeVisible()

    // One place per shot, each holding its own photo — and the review says what was made.
    const slots = page.getByTestId('captured-photo')
    await expect(slots).toHaveCount(layout.photos)
    const sources = new Set<string>()
    for (let shot = 1; shot <= layout.photos; shot += 1) {
      const slot = slots.nth(shot - 1)
      await expect(slot).toContainText(`Photo ${shot}`)
      sources.add(String(await slot.getByRole('img').getAttribute('src')))
    }
    expect(sources.size).toBe(layout.photos) // no photo stands in for another
    await expect(
      page.getByText(`Midnight · ${layout.pill} · ${layout.photos} photos`),
    ).toBeVisible()

    // The review shows a photo that was taken, in the photo's own shape; the camera is off screen
    // and its picker was never here.
    const big = page.getByTestId('review-photo')
    await expect(big).toBeVisible()
    await expect(page.getByLabel('Camera preview')).toHaveCount(0)
    await expect(page.getByLabel('Camera', { exact: true })).toHaveCount(0)
    expect(await big.getAttribute('src')).toBe([...sources][0])
    await expectSlotShape(page, layout.slot)

    // Pressing a place shows that photo; pressing the big one opens it whole.
    await page.getByRole('button', { name: `Show photo ${layout.photos}` }).click()
    await expect(big).toHaveAttribute('src', [...sources][layout.photos - 1] as string)
    await page.getByRole('button', { name: `Photo ${layout.photos}, see it bigger` }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: `Photo ${layout.photos}` })).toBeVisible()
    await expect(dialog.getByTestId('photo-large')).toBeVisible()
    await dialog.getByRole('button', { name: 'Close' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    await page.getByRole('button', { name: 'These are good' }).click()
    // The camera step is over: the finished photos are made and offered to take home.
    await expect(page).toHaveURL(/\/booth\/done$/)
    await expect(page.getByTestId('finished-photos').getByRole('img')).toHaveCount(
      layout.key === 'strip_2x6' ? 2 : 1,
    )
    await expect(page.getByTestId('delivery-qr')).toBeVisible()
    await expect
      .poll(() => page.getByTestId('delivery-qr').evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0)
    await expect.poll(async () => (await visit(page))?.state).toBe('delivered')
  })
}

/** Every screen this booth has to run on. */
const SIZES = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1366x768', width: 1366, height: 768 },
  { name: '1080x1920 kiosk', width: 1080, height: 1920 },
  { name: '390x844 phone', width: 390, height: 844 },
  { name: '640x360 short', width: 640, height: 360 },
] as const

test('the booth fits every screen it has to run on, and the picture stays useful', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await pairAndSignIn(page)
  await settings(page, { countdown: 10 }) // long enough to measure between photos
  await openBooth(page)
  await page.getByRole('tab', { name: '4×6' }).click()
  await chooseFrame(page, 'Midnight')
  await expect(page.getByLabel('Camera preview')).toBeVisible()

  const measured: Record<string, { width: number; height: number; overflow: number }> = {}
  for (const size of SIZES) {
    await page.setViewportSize({ width: size.width, height: size.height })
    const frame = page.getByTestId('photo-frame')
    await expect(frame).toBeVisible()
    const box = (await frame.boundingBox()) as { width: number; height: number }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    measured[size.name] = { ...box, overflow }

    expect(overflow, size.name).toBeLessThanOrEqual(1) // nothing pushes the page sideways
    expect(box.width, size.name).toBeLessThanOrEqual(size.width)
    expect(box.height, size.name).toBeLessThanOrEqual(size.height)
    expect(box.width, size.name).toBeGreaterThan(100) // never a few pixels of picture
    expect(box.height, size.name).toBeGreaterThan(100)
    // 4×6 keeps an upright 555 × 740 of each photo, whatever the screen is shaped like.
    expect(box.width / box.height, size.name).toBeCloseTo(555 / 740, 1)
    // The way out is still there, and the booth has no Admin chrome on it.
    await expect(page.getByRole('button', { name: 'Stop and start over' })).toBeVisible()
    await expect(page.getByRole('navigation')).toHaveCount(0)
  }
  console.log(`preview measurements: ${JSON.stringify(measured)}`)

  await page.setViewportSize({ width: 1280, height: 720 })
  await page.getByRole('button', { name: 'Stop and start over' }).click()
  await settings(page, { countdown: 1 })
})

test('the review fits a phone and a short screen, with the photo the biggest thing on it', async ({
  page,
}) => {
  await pairAndSignIn(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await openBooth(page)
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')
  await waitForPhotos(page, 2)
  await expect(page.getByRole('heading', { name: 'All photos taken' })).toBeVisible()

  for (const size of [
    { width: 390, height: 844 },
    { width: 640, height: 360 },
  ]) {
    await page.setViewportSize(size)
    const big = (await page.getByTestId('photo-frame').boundingBox()) as {
      width: number
      height: number
    }
    expect(big.width).toBeGreaterThan(100)
    expect(big.height).toBeGreaterThan(100)
    expect(big.width / big.height).toBeCloseTo(810 / 540, 1)
    // The thumbnails are a strip, not the screen: each one is far smaller than the big picture.
    const thumb = (await page.getByTestId('captured-photo').first().boundingBox()) as {
      height: number
    }
    expect(thumb.height).toBeLessThan(big.height)
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1)
    await expect(page.getByRole('button', { name: 'These are good' })).toBeVisible()
  }
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.getByRole('button', { name: 'These are good' }).click()
})

test('the countdown shown is the one the event asks for', async ({ page }) => {
  await pairAndSignIn(page)
  await settings(page, { countdown: 4 })
  await openBooth(page)
  await chooseFrame(page, 'Midnight')
  const countdown = page.getByTestId('countdown')
  await expect(countdown).toHaveText('4')
  await expect(countdown).toHaveText('3')
  await expect(countdown).toHaveText('2')
  await page.getByRole('button', { name: 'Stop and start over' }).click()
  await settings(page, { countdown: 1 }) // back to the quick countdown for the rest of the runs
})

test('the live picture follows the mirror setting; the photo itself is never flipped', async ({
  page,
}) => {
  await pairAndSignIn(page)
  await settings(page, { mirror: true })
  await openBooth(page)
  await chooseFrame(page, 'Midnight')
  const preview = page.getByLabel('Camera preview')
  await expect(preview).toHaveAttribute('data-mirrored', '')
  await expect(preview).toHaveCSS('transform', 'matrix(-1, 0, 0, 1, 0, 0)')
  await page.getByRole('button', { name: 'Stop and start over' }).click()

  await settings(page, { mirror: false })
  await openBooth(page)
  await chooseFrame(page, 'Midnight')
  await expect(page.getByLabel('Camera preview')).not.toHaveAttribute('data-mirrored', '')
  await expect(page.getByLabel('Camera preview')).not.toHaveCSS('transform', 'matrix(-1, 0, 0, 1, 0, 0)')
  await page.getByRole('button', { name: 'Stop and start over' }).click()
  await settings(page, { mirror: true })
})

test('one photo can be taken again without changing the frame or the others', async ({ page }) => {
  await pairAndSignIn(page)
  await settings(page, { retake: 'per_photo' })
  await openBooth(page)
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')
  await waitForPhotos(page, 2)
  const before = await visit(page)

  await page.getByRole('button', { name: 'Photo 2 again' }).click()
  await expect(page.getByTestId('capture-progress')).toHaveText('Photo 2 of 2')
  await waitForPhotos(page, 2)
  const after = await visit(page)
  expect(after.expected_captures).toBe(before.expected_captures)
  expect(after.shots.map((shot) => shot.attempt_no)).toEqual([1, 2]) // only that photo moved on
  expect(after.shots.every((shot) => shot.done)).toBe(true)
  await page.getByRole('button', { name: 'These are good' }).click()
})

test('an event that allows no retakes offers none', async ({ page }) => {
  await pairAndSignIn(page)
  await settings(page, { retake: 'none' })
  await openBooth(page)
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')
  await waitForPhotos(page, 2)
  await expect(page.getByRole('button', { name: /again/ })).toHaveCount(0)
  await page.getByRole('button', { name: 'These are good' }).click()
  await settings(page, { retake: 'per_photo' })
})

test('a reload in the middle of a session goes on where it stopped', async ({ page }) => {
  await pairAndSignIn(page)
  await openBooth(page)
  await page.getByRole('tab', { name: '4×6' }).click()
  await chooseFrame(page, 'Midnight')
  await waitForPhotos(page, 2)

  await page.reload()
  await expect(page.getByTestId('capture-progress')).toHaveText('Photo 3 of 4')
  await waitForPhotos(page, 4)
  const finished = await visit(page)
  // Four photos, four shots: the reload neither repeated nor skipped one.
  expect(finished.shots.map((shot) => shot.shot_index)).toEqual([1, 2, 3, 4])
  expect(finished.shots.every((shot) => shot.done && shot.attempt_no === 1)).toBe(true)
  await page.getByRole('button', { name: 'These are good' }).click()
})

test('going back to the frames and choosing again starts one visit, not two', async ({ page }) => {
  await pairAndSignIn(page)
  await openBooth(page)
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')
  const first = await visit(page)
  await waitForPhotos(page, 1)

  await page.goBack()
  await expect(page.getByTestId('frame-carousel')).toBeVisible()
  await chooseFrame(page, 'Minimal Light')
  const second = await visit(page)
  expect(second.id).not.toBe(first.id) // a new visit, with its own photos
  expect(second.taken).toBe(0)
  await waitForPhotos(page, 2)
  // The first visit is over: starting the second one ended it.
  const stale = await page.request.get(`/api/booth/sessions/${first.id}`)
  expect(stale.status()).toBe(200)
  expect((await stale.json()).state).toBe('abandoned')
  await page.getByRole('button', { name: 'These are good' }).click()
})

test('a blocked camera says so and works after it is allowed', async ({ page }) => {
  await pairAndSignIn(page)
  // The real camera path, refused exactly as a browser refuses it.
  await page.addInitScript(() => {
    let blocked = true
    const denied = () => {
      const error = new Error('Permission denied')
      error.name = 'NotAllowedError'
      return Promise.reject(error)
    }
    const canvas = document.createElement('canvas')
    canvas.width = 640
    canvas.height = 480
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [{ kind: 'videoinput', deviceId: 'fake', label: 'Fake' }],
        getUserMedia: async () => {
          if (blocked) return denied()
          const context = canvas.getContext('2d')
          if (context) {
            context.fillStyle = '#3366aa'
            context.fillRect(0, 0, canvas.width, canvas.height)
          }
          return canvas.captureStream(10)
        },
      },
    })
    ;(window as unknown as { pbAllowCamera: () => void }).pbAllowCamera = () => {
      blocked = false
    }
  })
  await page.goto('/booth/frames')
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('The camera is blocked for this booth')
  await expect(page.getByTestId('capture-progress')).toHaveText('Photo 1 of 2')
  expect((await visit(page)).taken).toBe(0) // nothing was invented while it was blocked

  await page.evaluate(() => (window as unknown as { pbAllowCamera: () => void }).pbAllowCamera())
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(alert).toHaveCount(0)
  await waitForPhotos(page, 2)
  await page.getByRole('button', { name: 'These are good' }).click()
})

test('a booth with no camera explains it and offers a way out', async ({ page }) => {
  await pairAndSignIn(page)
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [],
        getUserMedia: async () => {
          const error = new Error('no camera')
          error.name = 'NotFoundError'
          return Promise.reject(error)
        },
      },
    })
  })
  await page.goto('/booth/frames')
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')
  await expect(page.getByRole('alert')).toContainText('No camera is connected to this booth')
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
  await page.getByRole('button', { name: 'Start over', exact: true }).click()
  await expect(page).toHaveURL(/\/booth$/)
})

test('a camera unplugged in the middle of a session is reported, not ignored', async ({ page }) => {
  await pairAndSignIn(page)
  await page.addInitScript(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 640
    canvas.height = 480
    let stream: MediaStream | null = null
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [{ kind: 'videoinput', deviceId: 'fake', label: 'Fake' }],
        getUserMedia: async () => {
          const context = canvas.getContext('2d')
          if (context) {
            context.fillStyle = '#227744'
            context.fillRect(0, 0, canvas.width, canvas.height)
          }
          stream = canvas.captureStream(10)
          return stream
        },
      },
    })
    ;(window as unknown as { pbUnplugCamera: () => void }).pbUnplugCamera = () => {
      for (const track of stream?.getTracks() ?? []) track.stop()
    }
  })
  await page.goto('/booth/frames')
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')
  await waitForPhotos(page, 1)

  await page.evaluate(() => (window as unknown as { pbUnplugCamera: () => void }).pbUnplugCamera())
  await expect(page.getByRole('alert')).toContainText('The camera was disconnected', {
    timeout: 20_000,
  })
  const stalled = await visit(page)
  expect(stalled.taken).toBe(1) // the missing photo was never faked
  await page.getByRole('button', { name: 'Start over', exact: true }).click()
  await expect(page).toHaveURL(/\/booth$/)
})

test('the participant API keeps the visit to its own device', async ({ page, browser }) => {
  await pairAndSignIn(page)
  await openBooth(page)
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')
  const mine = await visit(page)

  const stranger = await browser.newContext()
  try {
    const other = await stranger.newPage()
    await pairAndSignIn(other)
    expect((await other.request.get(`/api/booth/sessions/${mine.id}`)).status()).toBe(404)
    expect(await (await other.request.get('/api/booth/sessions/current')).json()).toBeNull()
  } finally {
    await stranger.close()
  }
  await page.getByRole('button', { name: 'Stop and start over' }).click()
})

test('an unattended booth ends the visit by itself and goes back to the start', async ({ page }) => {
  test.setTimeout(120_000) // the booth waits out the event's own inactivity time
  await pairAndSignIn(page)
  // The shortest wait the profile allows, so the booth gives up quickly.
  await settings(page, { inactivity: 30 }) // the shortest the profile allows
  await openBooth(page)
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')
  await waitForPhotos(page, 1)
  const left = await visit(page)

  // Nobody touches the booth from here on.
  await expect(page).toHaveURL(/\/booth$/, { timeout: 60_000 })
  const ended = await page.request.get(`/api/booth/sessions/${left.id}`)
  expect((await ended.json()).state).toBe('cancelled')
  expect(await visit(page)).toBeNull()
  await settings(page, { inactivity: 120 })
})

test('the event the later specs expect is active again', async ({ page }) => {
  await pairAndSignIn(page)
  await profileRow(page, PERSISTED.copy)
    .getByRole('button', { name: `Activate ${PERSISTED.copy}`, exact: true })
    .click()
  await expect(profileRow(page, PERSISTED.copy).getByText('Active', { exact: true })).toBeVisible()
})

test('photos and the event survive a backend restart @after-restart', async ({ page }) => {
  await pairAndSignIn(page)
  // The booth re-paired after the restart: the event, its frames and the camera still work.
  await openBooth(page)
  await expect(page.getByRole('heading', { name: 'Choose your frame' })).toBeVisible()
  await page.getByRole('tab', { name: '3×4' }).click()
  await chooseFrame(page, 'Midnight')
  await waitForPhotos(page, 2, 45_000) // this event counts down 5 seconds per photo
  await expect(page.getByRole('heading', { name: 'All photos taken' })).toBeVisible()
  await page.getByRole('button', { name: 'These are good' }).click()
})
