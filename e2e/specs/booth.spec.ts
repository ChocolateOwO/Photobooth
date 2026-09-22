import { expect, test, type Page } from '@playwright/test'

import { pairAndSignIn, PERSISTED, profileRow } from './support/admin'

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
  await page.getByRole('checkbox', { name: 'Allow “Surprise me” random frame' }).check()
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)

  await page.goto('/admin')
  await profileRow(page, PROFILE).getByRole('button', { name: `Activate ${PROFILE}` }).click()
  await expect(page.getByRole('status')).toHaveText(`${PROFILE} is now the active profile.`)
})

test('a profile without frames can not be activated and says so on its row', async ({ page }) => {
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
  await expect(row.getByTestId('activation-error')).toContainText(
    'No frames are available to participants',
  )
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

test('the editor preview scrolls on its own on desktop and stacks on phones', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  await pairAndSignIn(page)
  await profileRow(page, PROFILE).getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  const preview = page.getByTestId('preview-column')
  await expect(preview).toHaveCSS('position', 'sticky')
  await expect(preview).toHaveCSS('overscroll-behavior-y', 'contain')
  await page.getByRole('button', { name: 'Frame selection' }).click()

  // Wheel over the preview: only the preview moves.
  const box = await preview.boundingBox()
  await page.mouse.move((box?.x ?? 0) + 40, (box?.y ?? 0) + 200)
  const pageBefore = await page.evaluate(() => window.scrollY)
  await page.mouse.wheel(0, 800)
  await expect.poll(() => preview.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
  expect(await page.evaluate(() => window.scrollY)).toBe(pageBefore)

  // Scrolling the editor keeps the preview in view.
  await page.mouse.move(80, 400)
  await page.mouse.wheel(0, 1500)
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(pageBefore)
  const after = await preview.boundingBox()
  expect(after?.y ?? -1).toBeGreaterThanOrEqual(0)
  expect((after?.y ?? 0) + (after?.height ?? 0)).toBeLessThanOrEqual(720 + 1)
  const wide = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(wide).toBeLessThanOrEqual(1)

  await page.setViewportSize({ width: 360, height: 800 })
  await expect(preview).toHaveCSS('position', 'static')
  const narrow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(narrow).toBeLessThanOrEqual(1)
})

test('the previously active profile is active again for the later specs', async ({ page }) => {
  await pairAndSignIn(page)
  await profileRow(page, PERSISTED.copy)
    .getByRole('button', { name: `Activate ${PERSISTED.copy}`, exact: true })
    .click()
  await expect(profileRow(page, PERSISTED.copy).getByText('Active', { exact: true })).toBeVisible()
})
