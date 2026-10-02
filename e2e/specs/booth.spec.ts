import { join } from 'node:path'

import { expect, test, type Locator, type Page } from './support/fixtures'

import { fixturesDir, pairAndSignIn, PERSISTED, profileRow } from './support/admin'

// Serial: one profile is prepared, activated and then used by the participant screen.
test.describe.configure({ mode: 'serial' })

const PROFILE = 'E2E Booth'
const EMPTY = 'E2E No frames'
// Every frame of the chosen sizes (3×4 and 2×6), in the booth's stable order: sizes in catalogue
// order, then built-in frames first and names A-Z. (No frames are uploaded before this spec.)
const OFFERED = [
  { name: 'Celebration Gold', label: '3×4', summary: '3×4 • 2 photos' },
  { name: 'Midnight', label: '3×4', summary: '3×4 • 2 photos' },
  { name: 'Minimal Light', label: '3×4', summary: '3×4 • 2 photos' },
  { name: 'Celebration Gold', label: '2×6', summary: '2×6 • 6 photos • 2 strips' },
  { name: 'Midnight', label: '2×6', summary: '2×6 • 6 photos • 2 strips' },
  { name: 'Minimal Light', label: '2×6', summary: '2×6 • 6 photos • 2 strips' },
] as const

function sizePill(page: Page, label: string) {
  return page.getByRole('group', { name: 'Photo sizes available' }).getByRole('button', { name: new RegExp(`^${label}`) })
}

test('the organizer chooses photo sizes, the countdown and Surprise me', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: 'New profile' }).click()
  await page.getByLabel('Profile name').fill(PROFILE)
  await page.getByLabel('Title', { exact: true }).fill('Pick a frame')
  // A new profile offers every size; the Event Profile has no per-frame controls at all.
  for (const label of ['3×4', '4×6', '2×6']) {
    await expect(sizePill(page, label)).toHaveAttribute('aria-pressed', 'true')
    await expect(sizePill(page, label)).toHaveAccessibleName(`${label}, 3 frames`)
  }
  await expect(page.getByLabel('Search frames')).toHaveCount(0)
  await expect(page.getByRole('switch', { name: /to participants$/ })).toHaveCount(0)
  await sizePill(page, '4×6').click()
  await expect(sizePill(page, '4×6')).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByTestId('available-frames-summary')).toHaveText('6 frames available to participants.')

  const countdown = page.getByRole('spinbutton', { name: 'Countdown before each photo' })
  await expect(countdown).toHaveValue('5')
  await page.getByRole('button', { name: 'Increase countdown' }).click()
  await countdown.focus()
  await page.keyboard.press('ArrowUp')
  await expect(countdown).toHaveValue('7')
  await page.getByRole('switch', { name: 'Allow “Surprise me” random frame' }).check()
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)

  await page.goto('/admin')
  await expect(profileRow(page, PROFILE).getByTestId('profile-sizes')).toHaveText('Photo sizes: 3×4, 2×6')
  await profileRow(page, PROFILE).getByRole('button', { name: `Activate ${PROFILE}` }).click()
  await expect(page.getByRole('status')).toHaveText(`${PROFILE} is now the active profile.`)
  const menu = (await (await page.request.get('/api/booth/frames')).json()) as { countdown_seconds: number }
  expect(menu.countdown_seconds).toBe(7) // ready for the capture step
})

test('a profile without photo sizes can not be activated and says so in a centred pop-up', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: 'New profile' }).click()
  await page.getByLabel('Profile name').fill(EMPTY)
  await page.getByLabel('Title', { exact: true }).fill('Nothing yet')
  for (const label of ['3×4', '4×6', '2×6']) await sizePill(page, label).click()
  await expect(page.getByRole('alert').filter({ hasText: 'No photo size is chosen' })).toBeVisible()
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)
  await page.goto('/admin')
  const row = profileRow(page, EMPTY)
  await row.getByRole('button', { name: `Activate ${EMPTY}` }).click()
  const refused = page.getByRole('alertdialog', { name: `${EMPTY} can not be activated` })
  await expect(refused).toContainText('No photo sizes are available to participants')
  await expect(refused.getByRole('link', { name: `Choose photo sizes for ${EMPTY}` })).toBeVisible()
  await refused.getByRole('button', { name: 'Close' }).click()
  await expect(refused).toHaveCount(0)
  await expect(row.getByRole('button', { name: `Activate ${EMPTY}` })).toBeFocused()
  await expect(profileRow(page, PROFILE).getByText('Active', { exact: true })).toBeVisible()
})
/** Everything about the frame in view: what it is, and whether it is the only whole slide. */
async function inView(page: Page): Promise<{ label: string; whole: string[] }> {
  return page.evaluate(() => {
    const track = document.querySelector('[data-testid="frame-carousel"] ul')
    if (!track) return { label: '', whole: [] } // not painted yet: the caller polls
    const box = track.getBoundingClientRect()
    const whole = Array.from(track.children)
      .filter((slide) => {
        const rect = slide.getBoundingClientRect()
        return rect.top >= box.top - 2 && rect.bottom <= box.bottom + 2
      })
      .map((slide) => slide.getAttribute('aria-label') ?? '')
    const current = track.querySelector('[data-current]')?.getAttribute('aria-label') ?? ''
    return { label: current, whole }
  })
}

async function settledOn(page: Page, label: string) {
  // One gesture settles on exactly one frame, and that frame is the one the carousel is on.
  await expect.poll(async () => (await inView(page)).label, { timeout: 5_000 }).toBe(label)
  await expect.poll(async () => (await inView(page)).whole).toEqual([label])
}

/**
 * A real finger swipe: Chromium synthesizes the touch gesture, so the browser scrolls and snaps
 * exactly as it does on the booth screen. `up` is the participant's finger moving up, which
 * brings the next frame in.
 */
async function swipe(page: Page, direction: 'up' | 'down') {
  const cdp = await page.context().newCDPSession(page)
  // The whole gesture stays inside the track, whatever the screen size.
  const box = await page.getByTestId('frame-carousel').locator('ul').boundingBox()
  const at = { x: (box?.x ?? 0) + (box?.width ?? 0) / 2, y: (box?.y ?? 0) + (box?.height ?? 0) / 2 }
  // Past the middle of the frame, so the gesture carries on to the next one.
  const reach = (box?.height ?? 0) * 0.3
  const distance = direction === 'up' ? -2 * reach : 2 * reach
  const start = Math.round(at.y - distance / 2)
  const point = (y: number) => [{ x: Math.round(at.x), y, radiusX: 12, radiusY: 12, force: 1 }]
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: point(start) })
  for (let step = 1; step <= 10; step++) {
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchMove',
      touchPoints: point(Math.round(start + (distance * step) / 10)),
    })
    await page.waitForTimeout(16)
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await cdp.detach()
}

function slideLabel(index: number): string {
  const offered = OFFERED[index]
  return `${offered?.name ?? ''}, ${index + 1} of ${OFFERED.length}`
}

test('participants move through full-size frames one at a time, then confirm and start', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/booth/frames')
  await expect(page.getByRole('heading', { name: 'Choose your frame' })).toBeVisible()
  const tabs = page.getByRole('tab')
  await expect(tabs).toHaveText(['All', '3×4', '2×6'])
  await expect(tabs.first()).toHaveAttribute('aria-selected', 'true')

  // The old grid of small cards is gone: one frame fills the screen, with its own details.
  await expect(page.getByRole('list', { name: 'Frames' })).toHaveCount(0)
  const slides = page.getByTestId('frame-slide')
  await expect(slides).toHaveCount(OFFERED.length)
  await settledOn(page, slideLabel(0))
  const first = slides.first()
  await expect(first.getByText(OFFERED[0]?.name ?? '', { exact: true })).toBeVisible()
  await expect(first.getByText(OFFERED[0]?.summary ?? '', { exact: true })).toBeVisible()
  await expect(first.getByText(`1 of ${OFFERED.length}`)).toBeVisible()
  await expect(first.getByRole('button', { name: 'Use this frame' })).toBeVisible()
  expect((await first.getByRole('button', { name: 'Use this frame' }).boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(64)
  await expect(page.getByText('Swipe or scroll to see the next frame')).toBeVisible()

  // The rendered sample loads from the booth API and is shown whole, in its own proportions.
  const sample = first.getByRole('img')
  await expect.poll(() => sample.evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 20_000 }).toBeGreaterThan(0)
  expect(await sample.getAttribute('src')).toMatch(/^\/api\/booth\/frames\//)
  const fits = async (image: Locator) =>
    image.evaluate((img: HTMLImageElement) => {
      const box = (img.parentElement as HTMLElement).getBoundingClientRect()
      const rect = img.getBoundingClientRect()
      return {
        ratio: rect.width / rect.height,
        natural: img.naturalWidth / img.naturalHeight,
        inside: rect.width <= box.width + 1 && rect.height <= box.height + 1,
        big: rect.height / box.height,
      }
    })
  const portraitFit = await fits(sample)
  expect(portraitFit.ratio).toBeCloseTo(portraitFit.natural, 1) // never stretched or cropped
  expect(portraitFit.inside).toBe(true)
  expect(portraitFit.big).toBeGreaterThan(0.8) // as large as the space allows

  // Nothing about where frames come from, and no admin actions.
  for (const word of ['Built-in', 'Uploaded', 'Replace', 'Delete', 'Rename']) {
    await expect(page.getByText(word, { exact: false })).toHaveCount(0)
  }

  // The mouse wheel moves one frame and settles it in the middle.
  const stage = await page.getByTestId('frame-carousel').boundingBox()
  const centre = { x: (stage?.x ?? 0) + (stage?.width ?? 0) / 2, y: (stage?.y ?? 0) + (stage?.height ?? 0) / 2 }
  await page.mouse.move(centre.x, centre.y)
  await page.mouse.wheel(0, 400)
  await settledOn(page, slideLabel(1))
  await expect(page.getByText('Swipe or scroll to see the next frame')).toHaveCount(0)

  // Previous/Next buttons and the arrow keys move one frame too.
  await page.getByRole('button', { name: 'Next frame' }).click()
  await settledOn(page, slideLabel(2))
  await page.getByRole('button', { name: 'Previous frame' }).click()
  await settledOn(page, slideLabel(1))
  await page.getByRole('button', { name: 'Next frame' }).focus()
  await page.keyboard.press('ArrowDown')
  await settledOn(page, slideLabel(2))
  await page.keyboard.press('ArrowUp')
  await settledOn(page, slideLabel(1))
  // The page itself never drifts while the carousel moves.
  expect(await page.evaluate(() => window.scrollY)).toBe(0)

  // A different aspect ratio (the 2×6 strip) is also shown whole.
  await page.getByRole('button', { name: `Show ${OFFERED[4]?.name ?? ''}` }).nth(1).click()
  await settledOn(page, slideLabel(4))
  const strip = slides.nth(4).getByRole('img')
  await expect.poll(() => strip.evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 20_000 }).toBeGreaterThan(0)
  const stripFit = await fits(strip)
  expect(stripFit.ratio).toBeCloseTo(stripFit.natural, 1)
  expect(stripFit.inside).toBe(true)
  expect(stripFit.ratio).toBeLessThan(portraitFit.ratio) // a much taller, narrower frame

  // Moving never chooses anything, and no bar sits under the carousel.
  await expect(page.getByText(/^Selected:/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Start with this frame' })).toHaveCount(0)
  expect(await page.evaluate(() => sessionStorage.getItem('pb.booth.chosenFrame'))).toBeNull()

  // A size filter shows only that size and starts again at its first frame.
  await page.getByRole('tab', { name: '2×6' }).click()
  await expect(slides).toHaveCount(3)
  await settledOn(page, `${OFFERED[3]?.name ?? ''}, 1 of 3`)
  await expect(slides.first().getByText('1 of 3')).toBeVisible()
  await page.getByRole('tab', { name: 'All' }).click()
  await settledOn(page, slideLabel(0))

  // "Use this frame" only asks, in a centred pop-up over the carousel.
  await page.getByRole('button', { name: `Show ${OFFERED[4]?.name ?? ''}` }).nth(1).click()
  await settledOn(page, slideLabel(4))
  await slides.nth(4).getByRole('button', { name: 'Use this frame' }).click()
  const question = page.getByRole('dialog', { name: 'Use this frame?' })
  await expect(question).toBeVisible()
  await expect(question.getByText(OFFERED[4]?.name ?? '', { exact: true })).toBeVisible()
  await expect(question.getByText(OFFERED[4]?.summary ?? '', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem('pb.booth.chosenFrame'))).toBeNull()
  // Centred, compact, and no second large copy of the frame.
  const box = await question.boundingBox()
  const view = page.viewportSize() ?? { width: 0, height: 0 }
  expect(Math.abs((box?.x ?? 0) + (box?.width ?? 0) / 2 - view.width / 2)).toBeLessThanOrEqual(2)
  expect(Math.abs((box?.y ?? 0) + (box?.height ?? 0) / 2 - view.height / 2)).toBeLessThanOrEqual(2)
  expect(box?.height ?? view.height).toBeLessThan(view.height * 0.7)
  const thumb = await question.locator('img').boundingBox()
  expect(thumb?.height ?? 0).toBeLessThanOrEqual(130)
  // The main answer holds the focus and the focus stays inside the question.
  await expect(question.getByRole('button', { name: 'Start with this frame' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(question.getByRole('button', { name: 'Choose a different frame' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(question.getByRole('button', { name: 'Start with this frame' })).toBeFocused()

  // Escape, the backdrop and "Choose a different frame" keep nothing and stay on this frame.
  for (const leave of [
    async () => page.keyboard.press('Escape'),
    async () => page.getByTestId('confirm-backdrop').click({ position: { x: 8, y: 8 } }),
    async () => question.getByRole('button', { name: 'Choose a different frame' }).click(),
  ]) {
    await expect(question).toBeVisible()
    await leave()
    await expect(question).toHaveCount(0)
    expect(await page.evaluate(() => sessionStorage.getItem('pb.booth.chosenFrame'))).toBeNull()
    await settledOn(page, slideLabel(4))
    // The button that asked has the focus again.
    await expect(slides.nth(4).getByRole('button', { name: 'Use this frame' })).toBeFocused()
    await page.keyboard.press('Enter')
  }

  // Only "Start with this frame" keeps the frame, and the photo session begins with it.
  await question.getByRole('button', { name: 'Start with this frame' }).click()
  await expect(page).toHaveURL(/\/booth\/capture$/)
  await expect(page.getByTestId('capture-progress')).toHaveText('Photo 1 of 6')
  // The browser remembers which frame it was, so coming back opens the carousel there.
  const kept = await page.evaluate(() => sessionStorage.getItem('pb.booth.chosenFrame'))
  expect(kept).toMatch(/^[0-9a-f-]{36}$/)
  // Stopping returns to the start screen; the frames open again on the frame chosen before.
  await page.getByRole('button', { name: 'Stop and start over' }).click()
  await expect(page).toHaveURL(/\/booth$/)
  await page.goto('/booth/frames')
  await settledOn(page, slideLabel(4))

  // Surprise me moves to one of the offered frames without asking anything.
  await page.getByRole('button', { name: 'Surprise me' }).click()
  const surprised = (await inView(page)).label
  expect(OFFERED.map((o, index) => slideLabel(index))).toContain(surprised)
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('a repeated tap on "Start with this frame" starts one visit only', async ({ page }) => {
  await pairAndSignIn(page)
  // A slow answer, so the second tap lands while the first is still on its way.
  const started: string[] = []
  await page.route('**/api/booth/sessions', async (route) => {
    started.push(route.request().postData() ?? '')
    await new Promise((resolve) => setTimeout(resolve, 900))
    await route.continue()
  })
  await page.goto('/booth/frames')
  await settledOn(page, slideLabel(0))
  await page.getByTestId('frame-slide').first().getByRole('button', { name: 'Use this frame' }).click()
  const start = page.getByRole('dialog', { name: 'Use this frame?' }).getByRole('button', { name: 'Start with this frame' })
  await start.click()
  await start.click({ force: true, timeout: 2_000 }).catch(() => undefined) // the button is disabled meanwhile
  await expect(page).toHaveURL(/\/booth\/capture$/)
  expect(started).toHaveLength(1)
  await page.unroute('**/api/booth/sessions')
  await page.getByRole('button', { name: 'Stop and start over' }).click()
})

test.describe('touchscreen', () => {
  test.use({ hasTouch: true })
  test('a swipe moves one frame', async ({ page }) => {
    await pairAndSignIn(page)
    await page.goto('/booth/frames')
    await page.getByTestId('frame-carousel').waitFor()
    await settledOn(page, slideLabel(0))
    await swipe(page, 'up') // the finger moves up: the next frame comes in
    await settledOn(page, slideLabel(1))
    await swipe(page, 'down')
    await settledOn(page, slideLabel(0))
    expect(await page.evaluate(() => window.scrollY)).toBe(0)
  })
})

test('a frame whose sample fails offers Retry without choosing it', async ({ page }) => {
  await pairAndSignIn(page)
  // Every sample render fails: the frame still shows its details, Retry and nothing selected.
  await page.route('**/api/booth/frames/*/preview.jpg*', (route) => route.fulfill({ status: 503, body: 'busy' }))
  await page.goto('/booth/frames')
  await settledOn(page, slideLabel(0))
  const retry = page.getByRole('button', { name: /^Retry/ }).first()
  await expect(retry).toBeVisible({ timeout: 20_000 })
  await retry.click()
  await expect(page.getByText(/^Selected:/)).toHaveCount(0)
  expect(await page.evaluate(() => sessionStorage.getItem('pb.booth.chosenFrame'))).toBeNull()
  await settledOn(page, slideLabel(0))
  await page.unroute('**/api/booth/frames/*/preview.jpg*')
})

test('the participant screen fits phone and tablet, portrait and landscape', async ({ page }) => {
  await pairAndSignIn(page)
  for (const size of [
    { width: 360, height: 800 }, // phone portrait
    { width: 800, height: 360 }, // phone landscape
    { width: 1080, height: 1920 }, // booth portrait
    { width: 1280, height: 800 }, // tablet landscape
  ]) {
    await page.setViewportSize(size)
    await page.goto('/booth/frames')
    await expect(page.getByRole('heading', { name: 'Choose your frame' })).toBeVisible()
    await settledOn(page, slideLabel(0))
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, `${size.width}x${size.height}`).toBeLessThanOrEqual(1)
    const choose = page.getByTestId('frame-slide').first().getByRole('button', { name: 'Use this frame' })
    await expect(choose).toBeVisible()

    // No bar under the carousel, so the frame itself gets most of the height.
    await expect(page.getByText(/^Selected:/)).toHaveCount(0)
    const sample = page.locator('[data-current] img').first()
    await expect
      .poll(() => sample.evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 20_000 })
      .toBeGreaterThan(0)
    const room = await page.evaluate(() => {
      const carousel = document.querySelector('[data-testid="frame-carousel"]') as HTMLElement
      const image = carousel.querySelector('[data-current] img') as HTMLElement
      return image.getBoundingClientRect().height / carousel.getBoundingClientRect().height
    })
    // A phone held sideways has little height to give; every other screen gives the frame most of it.
    expect(room, `${size.width}x${size.height}`).toBeGreaterThan(size.height < 420 ? 0.3 : 0.5)

    // The question fits on this screen too, with big enough answers.
    await choose.click()
    const question = page.getByRole('dialog', { name: 'Use this frame?' })
    const box = await question.boundingBox()
    expect((box?.x ?? -1) >= 0 && (box?.x ?? 0) + (box?.width ?? 0) <= size.width + 1).toBe(true)
    expect((box?.y ?? -1) >= 0 && (box?.y ?? 0) + (box?.height ?? 0) <= size.height + 1).toBe(true)
    for (const name of ['Start with this frame', 'Choose a different frame']) {
      const answer = await question.getByRole('button', { name }).boundingBox()
      expect(answer?.height ?? 0, `${name} at ${size.width}x${size.height}`).toBeGreaterThanOrEqual(44)
    }
    await page.keyboard.press('Escape')
    await expect(question).toHaveCount(0)
  }
  await page.setViewportSize({ width: 1280, height: 800 })
})

test('the editor preview stays still while the form scrolls, fits whole and stacks on phones', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  await pairAndSignIn(page)
  await profileRow(page, PROFILE).getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  const column = page.getByTestId('preview-column')
  const form = page.locator('form').filter({ has: page.getByRole('button', { name: 'Save profile' }) })
  const screen = page.getByTestId('preview-screen')
  await expect(screen).toBeVisible()
  // No scrollbar of its own: the logical screen is scaled to fit instead.
  await expect(column).toHaveCSS('overflow-y', 'hidden')
  expect(await column.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(1)
  await expect(page.getByText('Phone width')).toHaveCount(0)
  await expect(page.getByTestId('preview-viewport')).toHaveCount(1)
  // The preview sits below the header, whole, inside the window.
  const header = await page.getByRole('banner').boundingBox()
  const fitsWindow = async () => {
    const box = await screen.boundingBox()
    expect(box?.y ?? -1).toBeGreaterThanOrEqual((header?.y ?? 0) + (header?.height ?? 0))
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(720 + 1)
    return box
  }
  const start = await fitsWindow()
  // Portrait 1080 x 1920 by default, drawn whole at its own proportions.
  expect((start?.width ?? 0) / (start?.height ?? 1)).toBeCloseTo(1080 / 1920, 2)

  // Scroll the long form: it moves in its own column; the window and the preview do not move.
  const formBox = await form.boundingBox()
  await page.mouse.move((formBox?.x ?? 0) + 60, 500)
  await page.mouse.wheel(0, 900)
  await expect.poll(() => form.evaluate((el) => el.scrollTop)).toBeGreaterThan(300)
  await page.mouse.wheel(0, 1600)
  await expect.poll(() => form.evaluate((el) => el.scrollTop)).toBeGreaterThan(1200)
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
  let box = await fitsWindow()
  expect(Math.abs((box?.y ?? 0) - (start?.y ?? 0))).toBeLessThanOrEqual(1)
  expect(Math.abs((box?.x ?? 0) - (start?.x ?? 0))).toBeLessThanOrEqual(1)
  // A wheel over the preview moves nothing either (no scroll chaining).
  await page.mouse.move((start?.x ?? 0) + 20, (start?.y ?? 0) + 20)
  const formScroll = await form.evaluate((el) => el.scrollTop)
  await page.mouse.wheel(0, 600)
  await page.waitForTimeout(300)
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
  expect(await form.evaluate((el) => el.scrollTop)).toBe(formScroll)
  box = await fitsWindow()
  expect(Math.abs((box?.y ?? 0) - (start?.y ?? 0))).toBeLessThanOrEqual(1)

  // Landscape and a typed size change the drawing, which still fits whole.
  await page.getByRole('group', { name: 'Orientation' }).getByRole('button', { name: 'Landscape' }).click()
  await expect(page.getByTestId('preview-size')).toHaveText('1920 × 1080 px')
  box = await fitsWindow()
  expect((box?.width ?? 0) / (box?.height ?? 1)).toBeCloseTo(1920 / 1080, 2)
  await page.getByLabel('Preview width in pixels').fill('1280')
  await page.getByLabel('Preview height in pixels').fill('800')
  await expect(page.getByTestId('preview-size')).toHaveText('1280 × 800 px')
  box = await fitsWindow()
  expect((box?.width ?? 0) / (box?.height ?? 1)).toBeCloseTo(1280 / 800, 2)
  await page.getByRole('button', { name: 'Frame selection' }).click()
  await expect(screen.getByTestId('frame-carousel')).toBeVisible()
  // The preview asks in the same pop-up, inside the preview screen, with no bar under it.
  await expect(screen.getByText(/^Selected:/)).toHaveCount(0)
  await screen.getByTestId('frame-slide').first().getByRole('button', { name: 'Use this frame' }).click()
  const previewQuestion = screen.getByRole('dialog', { name: 'Use this frame?' })
  await expect(previewQuestion).toBeVisible()
  const previewBox = await previewQuestion.boundingBox()
  const screenBox = await screen.boundingBox()
  expect((previewBox?.x ?? 0) >= (screenBox?.x ?? 0) - 1).toBe(true)
  expect((previewBox?.y ?? 0) >= (screenBox?.y ?? 0) - 1).toBe(true)
  await previewQuestion.getByRole('button', { name: 'Choose a different frame' }).click()
  await expect(previewQuestion).toHaveCount(0)
  expect(await column.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(1)
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(wide).toBeLessThanOrEqual(1)

  // Narrow window: one stacked column, normal page scrolling, the same single preview.
  await page.setViewportSize({ width: 360, height: 800 })
  await expect(form).toHaveCSS('overflow-y', 'visible')
  await expect(page.getByTestId('preview-viewport')).toHaveCount(1)
  const narrowBox = await screen.boundingBox()
  expect((narrowBox?.x ?? -1) >= 0 && (narrowBox?.x ?? 0) + (narrowBox?.width ?? 0) <= 360).toBe(true)
  const narrow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(narrow).toBeLessThanOrEqual(1)
  expect(await page.evaluate(() => document.documentElement.scrollHeight > window.innerHeight)).toBe(true)
})
async function expectOnlyStartScreen(page: Page) {
  const screen = page.getByRole('group', { name: 'Start screen' })
  await expect(screen).toBeVisible()
  await expect(screen.getByRole('button')).toHaveCount(1)
  await expect(screen.getByRole('textbox')).toHaveCount(0)
  for (const gone of [/email/i, /\bback\b/i, /\bprint\b/i, /frames? to choose/i, /photos are ready/i, /paper/i]) {
    await expect(screen.getByText(gone)).toHaveCount(0)
  }
  return screen
}

test('the real booth start screen shows the profile look and leads to the frame choice', async ({ page }) => {
  await pairAndSignIn(page)
  // The active profile has no logo or background yet: the neutral mark, no broken image.
  await page.goto('/booth')
  let screen = await expectOnlyStartScreen(page)
  await expect(screen.getByRole('img', { name: 'Photobooth' })).toBeVisible()
  await expect(screen.getByRole('button')).toHaveText('Start')
  await expect(screen.getByText('Pick a frame')).toHaveCount(0) // the stored title is not shown

  // Give the profile a logo, a background and its own Start text.
  await page.goto('/admin')
  await profileRow(page, PROFILE).getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  await page.getByLabel('Start button text').fill('Tap to begin')
  await page.getByLabel('Logo image').setInputFiles(join(fixturesDir, 'logo.png'))
  await expect(page.getByRole('img', { name: 'Logo preview' })).toBeVisible()
  await page.getByLabel('Background image').setInputFiles(join(fixturesDir, 'background.jpg'))
  await expect(page.getByRole('img', { name: 'Background preview' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save profile' })).toBeEnabled({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toBeVisible()
  const previewButton = page.getByTestId('event-preview').getByTestId('start-screen').getByRole('button')
  const previewColour = await previewButton.evaluate((el) => getComputedStyle(el).backgroundColor)

  await page.goto('/booth')
  screen = await expectOnlyStartScreen(page)
  // Same shared component as the admin preview, with the same theme colours.
  await expect(screen.getByTestId('start-screen')).toBeVisible()
  const start = screen.getByRole('button', { name: 'Tap to begin' })
  await expect(start).toHaveCSS('background-color', previewColour)
  const logo = screen.getByRole('img', { name: 'Event logo' })
  await expect.poll(() => logo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(256)
  expect(await logo.getAttribute('src')).toMatch(/^\/api\/booth\/start\/logo\?v=[0-9a-f]{16}$/)
  const background = await screen.evaluate((el) => getComputedStyle(el).backgroundImage)
  expect(background).toMatch(/\/api\/booth\/start\/background\?v=[0-9a-f]{16}/)
  const served = await page.request.get(/url\("?([^")]+)/.exec(background)?.[1] ?? '')
  expect(served.status()).toBe(200)
  expect(served.headers()['content-type']).toBe('image/jpeg')
  // Centred, fills the screen, nothing sideways.
  const box = await start.boundingBox()
  const viewport = page.viewportSize()
  expect(Math.abs((box?.x ?? 0) + (box?.width ?? 0) / 2 - (viewport?.width ?? 0) / 2)).toBeLessThan(4)
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
  ).toBeLessThanOrEqual(1)

  // No asset ids or admin data in what the booth receives.
  const menu = await (await page.request.get('/api/booth/frames')).text()
  for (const secret of ['asset_id', 'storage', 'revision', 'Pick a frame', PROFILE]) {
    expect(menu).not.toContain(secret)
  }

  await start.click()
  await expect(page).toHaveURL(/\/booth\/frames$/)
  await expect(page.getByRole('heading', { name: 'Choose your frame' })).toBeVisible()
})

test('a maximum-length Start text stays whole on a narrow screen', async ({ page }) => {
  const longText = 'W'.repeat(40) // the longest allowed text, as one unbreakable word
  await pairAndSignIn(page)
  await profileRow(page, PROFILE).getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  await page.getByLabel('Start button text').fill(longText)
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toBeVisible()

  for (const width of [360, 1080]) {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/booth')
    const start = page.getByRole('group', { name: 'Start screen' }).getByRole('button', { name: longText })
    await expect(start).toBeVisible()
    const box = await start.boundingBox()
    expect(box?.x ?? -1).toBeGreaterThanOrEqual(0)
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width + 1)
    // The whole label is inside the button (nothing cut off).
    expect(await start.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1)
    expect(await start.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(1)
  }

  // Back to the short text for the specs that follow.
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto('/admin')
  await profileRow(page, PROFILE).getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  await page.getByLabel('Start button text').fill('Tap to begin')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toBeVisible()
})

test('the booth start screen needs the paired device', async ({ browser }) => {
  const context = await browser.newContext({ baseURL: 'http://127.0.0.1:5192' })
  const page = await context.newPage()
  try {
    await page.goto('/booth')
    await expect(page.getByRole('alert')).toContainText('not paired')
    expect((await page.request.get('/api/booth/start/logo')).status()).toBe(401)
  } finally {
    await context.close()
  }
})

test('the booth start screen works after a backend restart @after-restart', async ({ page }) => {
  await pairAndSignIn(page) // pairing never survives a restart
  await page.goto('/booth')
  const screen = await expectOnlyStartScreen(page)
  const start = screen.getByRole('button', { name: PERSISTED.startText })
  await expect(start).toHaveCSS('background-color', 'rgb(242, 201, 76)')
  const logo = screen.getByRole('img', { name: 'Event logo' })
  await expect.poll(() => logo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(256)
  await expect
    .poll(() => screen.evaluate((el) => getComputedStyle(el).backgroundImage))
    .toMatch(/\/api\/booth\/start\/background\?v=/)
  await start.click()
  await expect(page.getByRole('heading', { name: 'Choose your frame' })).toBeVisible()
})

test('the previously active profile is active again for the later specs', async ({ page }) => {
  await pairAndSignIn(page)
  await profileRow(page, PERSISTED.copy)
    .getByRole('button', { name: `Activate ${PERSISTED.copy}`, exact: true })
    .click()
  await expect(profileRow(page, PERSISTED.copy).getByText('Active', { exact: true })).toBeVisible()
})
