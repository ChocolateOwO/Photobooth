import { join } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { fixturesDir, pairAndSignIn, PERSISTED, profileRow } from './support/admin'

// Serial: one profile is prepared, activated and then used by the participant screen.
test.describe.configure({ mode: 'serial' })

const PROFILE = 'E2E Booth'
const EMPTY = 'E2E No frames'
const OFFERED = [
  { name: 'Celebration Gold', label: '3×4', summary: '3×4 • 2 photos' },
  { name: 'Midnight', label: '2×6', summary: '2×6 • 6 photos • 2 strips' },
  { name: 'Minimal Light', label: '4×6', summary: '4×6 • 4 photos' },
] as const

function frameSwitch(page: Page, name: string, label: string) {
  return page.getByRole('switch', { name: `Show ${name} (${label}) to participants` })
}

async function shownOrder(page: Page): Promise<string[]> {
  return page
    .getByRole('list', { name: 'Frames shown to participants' })
    .getByTestId('available-frame-row')
    .allInnerTexts()
}

test('the organizer offers three frames in a chosen order, with Surprise me', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: 'New profile' }).click()
  await page.getByLabel('Profile name').fill(PROFILE)
  await page.getByLabel('Title', { exact: true }).fill('Pick a frame')
  for (const label of ['3×4', '4×6', '2×6']) {
    await page.getByRole('button', { name: `Disable all ${label}` }).click()
  }
  await expect(page.getByTestId('available-frames-summary')).toHaveText(
    '0 frames available to participants',
  )
  await expect(page.getByRole('alert').filter({ hasText: 'No frames are available' })).toBeVisible()
  // Switched on in a different order, then put in order with the Move buttons.
  await frameSwitch(page, 'Minimal Light', '4×6').check()
  await frameSwitch(page, 'Midnight', '2×6').check()
  await frameSwitch(page, 'Celebration Gold', '3×4').check()
  await page.getByRole('button', { name: 'Move Celebration Gold up' }).click()
  await page.getByRole('button', { name: 'Move Celebration Gold up' }).click()
  await page.getByRole('button', { name: 'Move Minimal Light down' }).click()
  const order = await shownOrder(page)
  expect(order.map((row) => OFFERED.findIndex((o) => row.includes(o.name)))).toEqual([0, 1, 2])
  await page.getByRole('switch', { name: 'Allow “Surprise me” random frame' }).check()
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)

  await page.goto('/admin')
  await profileRow(page, PROFILE).getByRole('button', { name: `Activate ${PROFILE}` }).click()
  await expect(page.getByRole('status')).toHaveText(`${PROFILE} is now the active profile.`)
})

test('a profile without frames can not be activated and says so in a centred pop-up', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: 'New profile' }).click()
  await page.getByLabel('Profile name').fill(EMPTY)
  await page.getByLabel('Title', { exact: true }).fill('Nothing yet')
  for (const label of ['3×4', '4×6', '2×6']) {
    await page.getByRole('button', { name: `Disable all ${label}` }).click()
  }
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)
  await page.goto('/admin')
  const row = profileRow(page, EMPTY)
  await row.getByRole('button', { name: `Activate ${EMPTY}` }).click()
  const refused = page.getByRole('alertdialog', { name: `${EMPTY} can not be activated` })
  await expect(refused).toContainText('No frames are available to participants')
  await expect(refused.getByRole('link', { name: `Choose frames for ${EMPTY}` })).toBeVisible()
  await refused.getByRole('button', { name: 'Close' }).click()
  await expect(refused).toHaveCount(0)
  await expect(row.getByRole('button', { name: `Activate ${EMPTY}` })).toBeFocused()
  await expect(profileRow(page, PROFILE).getByText('Active', { exact: true })).toBeVisible()
})

test('participants choose a frame: preview first, then confirm and start', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/booth/frames')
  await expect(page.getByRole('heading', { name: 'Choose your frame' })).toBeVisible()
  const tabs = page.getByRole('tab')
  await expect(tabs).toHaveText(['All', '3×4', '2×6', '4×6'])
  await expect(tabs.first()).toHaveAttribute('aria-selected', 'true')
  const list = page.getByRole('list', { name: 'Frames' })
  const cards = list.getByRole('button')
  await expect(cards).toHaveCount(4) // Surprise me + the three offered frames
  for (const [index, offered] of OFFERED.entries()) {
    await expect(cards.nth(index + 1)).toHaveAccessibleName(`${offered.name}, ${offered.summary}`)
  }
  // Rendered samples with photos load from the booth API.
  await expect
    .poll(() => list.locator('img').first().evaluate((img: HTMLImageElement) => img.naturalWidth), {
      timeout: 20_000,
    })
    .toBeGreaterThan(0)
  expect(await list.locator('img').first().getAttribute('src')).toMatch(/^\/api\/booth\/frames\//)
  // Nothing about where frames come from, and no admin actions.
  for (const word of ['Built-in', 'Uploaded', 'Replace', 'Delete', 'Rename']) {
    await expect(page.getByText(word, { exact: false })).toHaveCount(0)
  }
  const tall = await cards.nth(1).boundingBox()
  expect(tall?.height ?? 0).toBeGreaterThanOrEqual(64)

  // Filter tab
  await page.getByRole('tab', { name: '2×6' }).click()
  await expect(list.getByRole('button', { name: /^Midnight/ })).toBeVisible()
  await expect(list.getByRole('button', { name: /^Celebration Gold/ })).toHaveCount(0)
  await page.getByRole('tab', { name: 'All' }).click()

  // Tapping only opens the preview.
  await cards.nth(2).click()
  const dialog = page.getByRole('dialog', { name: 'Midnight' })
  await expect(dialog.getByText('2×6 • 6 photos • 2 strips')).toBeVisible()
  await expect(page.getByRole('status')).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Back' }).click()
  await expect(dialog).toHaveCount(0)
  await cards.nth(2).click()
  await dialog.getByRole('button', { name: 'Use this frame' }).click()
  await expect(page.getByRole('status')).toContainText('Selected: Midnight')
  const plan = await page.evaluate(() => sessionStorage.getItem('pb.booth.chosenFrame'))
  expect(JSON.parse(plan ?? '{}')).toMatchObject({ template_key: 'strip_2x6', captures: 6, outputs: 2 })
  await page.getByRole('button', { name: 'Start with this frame' }).click()
  await expect(page.getByText(/Ready: Midnight/)).toBeVisible()
  await page.getByRole('button', { name: 'Choose a different frame' }).click()
  await expect(page.getByRole('heading', { name: 'Choose your frame' })).toBeVisible()

  // Surprise me opens the same confirmation for one of the offered frames.
  await page.getByRole('button', { name: /Surprise me/ }).click()
  const surprise = page.getByRole('dialog')
  await expect(surprise).toBeVisible()
  const picked = await surprise.getByRole('heading').innerText()
  expect(OFFERED.map((o) => o.name)).toContain(picked)
})

test('the participant screen fits a phone without sideways scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await pairAndSignIn(page)
  await page.goto('/booth/frames')
  await expect(page.getByRole('heading', { name: 'Choose your frame' })).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
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
  await expect(screen.getByTestId('frame-gallery')).toBeVisible()
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
  await expect(start).toHaveCSS('background-color', 'rgb(170, 34, 68)')
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
