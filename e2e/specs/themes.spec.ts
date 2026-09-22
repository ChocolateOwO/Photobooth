import { join } from 'node:path'

import { expect, test, type Locator, type Page } from '@playwright/test'

import { fixturesDir, pairAndSignIn, profileRow } from './support/admin'

// Serial: later steps reopen the profile saved earlier on the same e2e instance.
test.describe.configure({ mode: 'serial' })

const PROFILE = 'E2E Themes'
const COPY = 'E2E Themes (copy)'
const LINK = '#FFD27A'
const FAMILIES = ['Minimal Light', 'Midnight', 'Celebration Gold'] as const
const LAYOUT_NAMES = ['3x4 print', '4x6 print (2x2 grid)', '2x6 photo strip'] as const
const LABELS = ['3×4', '4×6', '2×6'] as const

function goldSwitch(page: Page, label: string): Locator {
  return page.getByRole('switch', { name: `Show Celebration Gold (${label}) to participants` })
}

interface Catalog {
  default_preset: string
  presets: { id: string; name: string; tokens: Record<string, string> }[]
}

function rgb(hex: string): string {
  const n = (i: number) => parseInt(hex.slice(i, i + 2), 16)
  return `rgb(${n(1)}, ${n(3)}, ${n(5)})`
}

async function catalog(page: Page): Promise<Catalog> {
  const response = await page.request.get('/api/admin/themes')
  expect(response.status()).toBe(200)
  return (await response.json()) as Catalog
}

function preview(page: Page): Locator {
  return page.getByTestId('event-preview')
}

async function expectPreviewTokens(page: Page, tokens: Record<string, string>) {
  const view = preview(page)
  // The start screen: background, the Photobooth mark (no logo yet) and the Start button.
  await expect(view.getByRole('group', { name: 'Start screen preview' })).toHaveCSS(
    'background-color',
    rgb(tokens.background ?? ''),
  )
  const start = view.getByTestId('start-screen').getByRole('button')
  await expect(start).toHaveCSS('background-color', rgb(tokens.primary_bg ?? ''))
  await expect(start).toHaveCSS('color', rgb(tokens.primary_text ?? ''))
  await expect(view.getByRole('img', { name: 'Photobooth' })).toHaveCSS('color', rgb(tokens.heading ?? ''))
}

function mark(page: Page): Locator {
  return preview(page).getByRole('img', { name: 'Photobooth' })
}

test('built-in frames are there on a fresh setup and are read-only', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  await page.getByRole('group', { name: 'Show' }).getByRole('button', { name: 'Built-in' }).click()
  const rows = page.getByTestId('frame-row')
  await expect(rows).toHaveCount(FAMILIES.length * LAYOUT_NAMES.length)
  for (const family of FAMILIES) {
    const familyRows = rows.filter({ has: page.getByRole('heading', { name: family, exact: true }) })
    await expect(familyRows).toHaveCount(LAYOUT_NAMES.length)
    for (let i = 0; i < LAYOUT_NAMES.length; i++) {
      const row = familyRows.nth(i)
      await expect(row.getByText('Built-in', { exact: true })).toBeVisible()
      await expect(row.getByText('Read-only', { exact: true })).toBeVisible()
      await expect(row.getByRole('button', { name: /Replace|Rename|Delete/ })).toHaveCount(0)
      await expect(row.getByRole('img')).toHaveCount(1)
      await row.scrollIntoViewIfNeeded()
      await expect
        .poll(
          () => row.getByRole('img', { name: `${family} sample output` }).evaluate((img: HTMLImageElement) => img.naturalWidth),
          { timeout: 20_000 },
        )
        .toBeGreaterThan(0)
    }
  }
  // All nine packaged frames (three families x three layouts) are listed by the API.
  const frames = (await (await page.request.get('/api/admin/frames')).json()) as { builtin: boolean }[]
  expect(frames.filter((f) => f.builtin)).toHaveLength(9)
})

test('quick themes sit in one row of compact options with round colour dots', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: 'New profile' }).click()
  const options = page.getByTestId('theme-option')
  await expect(options).toHaveCount(7)
  const tops = await options.evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)))
  expect(new Set(tops).size).toBe(1) // one horizontal strip (it scrolls sideways if needed)
  for (const box of await options.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height))) {
    expect(box).toBeLessThanOrEqual(56)
  }
  const dots = options.first().locator('[data-swatch]')
  await expect(dots).toHaveCount(3)
  for (const radius of await dots.evaluateAll((els) => els.map((el) => getComputedStyle(el).borderRadius))) {
    expect(radius).toBe('50%')
  }
  const selected = options.filter({ has: page.getByRole('radio', { checked: true }) })
  await expect(selected).toHaveCount(1)
  await expect(selected).toHaveAttribute('data-selected', '')
  const selectedBorder = await selected.evaluate((el) => getComputedStyle(el).borderColor)
  const otherBorder = await options.nth(1).evaluate((el) => getComputedStyle(el).borderColor)
  expect(selectedBorder).toBe('rgb(47, 111, 214)')
  expect(otherBorder).not.toBe(selectedBorder)
  // Details never selects; one details view at a time.
  await page.getByRole('button', { name: 'View details of Sunset Coral' }).click()
  await expect(page.locator('[role="dialog"][aria-modal="true"]')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('radio', { name: /^Sunset Coral/ })).not.toBeChecked()
  // Clicking anywhere on the option (its invisible radio covers it) selects it.
  const coral = options.filter({ hasText: 'Sunset Coral' })
  const coralBox = await coral.getByRole('radio').boundingBox()
  const nameBox = await coral.getByText('Sunset Coral', { exact: true }).boundingBox()
  expect((coralBox?.width ?? 0) >= (nameBox?.width ?? 1)).toBe(true)
  await coral.getByRole('radio').click()
  await expect(page.getByRole('radio', { name: /^Sunset Coral/ })).toBeChecked()
})
test('a new profile starts with an accessible preset and built-in frames', async ({ page }) => {
  await pairAndSignIn(page)
  const themes = await catalog(page)
  expect(themes.presets.length).toBeGreaterThanOrEqual(6)
  const fallback = themes.presets.find((p) => p.id === themes.default_preset)
  await page.getByRole('link', { name: 'New profile' }).click()
  await expect(page.getByRole('radio', { name: new RegExp(`^${fallback?.name ?? ''}`) })).toBeChecked()
  await expect(page.getByTestId('contrast-ok')).toBeVisible()
  await expect(page.getByTestId('available-frames-summary')).toHaveText(
    '9 frames available to participants',
  )
  await expectPreviewTokens(page, fallback?.tokens ?? {})
  // The admin shell keeps its own colours.
  await expect(page.getByRole('heading', { name: 'New Event Profile' })).toHaveCSS('color', 'rgb(244, 246, 248)')
})

test('presets, background colours, undo, advanced colours and saving', async ({ page }) => {
  await pairAndSignIn(page)
  const themes = await catalog(page)
  const gold = themes.presets.find((p) => p.id === 'celebration_gold')
  expect(gold).toBeDefined()
  await page.getByRole('link', { name: 'New profile' }).click()
  await page.getByLabel('Profile name').fill(PROFILE)
  await page.getByLabel('Title', { exact: true }).fill('Theme party')

  // Compact tiles: details open without selecting anything.
  await page.getByRole('button', { name: 'View details of Neon Party' }).click()
  const details = page.getByRole('dialog', { name: 'Neon Party' })
  await expect(details.getByRole('row')).toHaveCount(35)
  await details.getByRole('button', { name: 'Close' }).click()
  await expect(details).toHaveCount(0)
  await expect(page.getByRole('radio', { name: /^Midnight Blue/ })).toBeChecked()

  // Quick theme: the whole preset, not two colours.
  await page.getByRole('radio', { name: /^Celebration Gold/ }).check()
  await expectPreviewTokens(page, gold?.tokens ?? {})

  // A light background gives a light page with dark text; a dark one the opposite.
  await page.getByLabel('Background image').setInputFiles(join(fixturesDir, 'bg_light.jpg'))
  await expect(page.getByText('Colors extracted from background')).toBeVisible()
  const swatches = page.getByRole('list', { name: 'Colours found in the background' })
  await expect(swatches.getByRole('listitem').first()).toBeVisible()
  const lightSwatches = await swatches.innerText()
  const heading = mark(page)
  const darkText = await heading.evaluate((el) => getComputedStyle(el).color)
  expect(darkText).not.toBe(rgb(gold?.tokens.heading ?? ''))

  await page.getByLabel('Background image').setInputFiles(join(fixturesDir, 'bg_dark.jpg'))
  // The new background gives a new palette and light text on a dark page.
  await expect
    .poll(() => heading.evaluate((el) => getComputedStyle(el).color), { timeout: 15_000 })
    .not.toBe(darkText)
  expect(await swatches.innerText()).not.toBe(lightSwatches)
  const lightText = await heading.evaluate((el) => getComputedStyle(el).color)

  // Undo returns to the theme before the last extraction (the light one).
  await page.getByRole('button', { name: 'Undo extracted theme' }).click()
  await expect(heading).toHaveCSS('color', darkText)
  await page.getByRole('button', { name: 'Re-extract colors' }).click()
  await expect(heading).toHaveCSS('color', lightText)

  // Back to a preset, then one hand-made colour with a contrast warning, and a reset.
  await page.getByRole('button', { name: 'Choose a preset instead' }).click()
  await page.getByRole('radio', { name: /^Celebration Gold/ }).check()
  await page.getByText('Advanced colors').click()
  await page.getByLabel('Headings hex value', { exact: true }).fill(gold?.tokens.background ?? '')
  await expect(page.getByTestId('contrast-warning')).toContainText('Headings: contrast 1.0:1')
  await page.getByRole('button', { name: 'Reset to selected preset' }).click()
  await expect(page.getByTestId('contrast-warning')).toHaveCount(0)
  await page.getByLabel('Links hex value', { exact: true }).fill(LINK)

  // Only the Celebration Gold frames stay available to participants, and save.
  for (const family of ['Minimal Light', 'Midnight']) {
    for (const label of LABELS) {
      await page.getByRole('switch', { name: `Show ${family} (${label}) to participants` }).uncheck()
    }
  }
  await expect(page.getByTestId('available-frames-summary')).toHaveText(
    '3 frames available to participants',
  )
  await page.getByRole('button', { name: 'Frame selection' }).click()
  const cards = preview(page).getByRole('list', { name: 'Frames' }).getByRole('button')
  await expect(cards).toHaveCount(3)
  await expect(cards.first()).toHaveAccessibleName(/^Celebration Gold, /)
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)

  await page.reload()
  await page.getByText('Advanced colors').click()
  await expect(page.getByLabel('Links hex value', { exact: true })).toHaveValue(LINK)
  await expect(goldSwitch(page, '2×6')).toBeChecked()
  await expect(page.getByRole('switch', { name: 'Show Midnight (2×6) to participants' })).not.toBeChecked()
})

test('duplicating a profile keeps its theme and frames', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('button', { name: `Duplicate ${PROFILE}`, exact: true }).click()
  await expect(profileRow(page, COPY)).toBeVisible()
  await page.getByRole('link', { name: `Edit ${COPY}`, exact: true }).click()
  await page.getByText('Advanced colors').click()
  await expect(page.getByLabel('Links hex value', { exact: true })).toHaveValue(LINK)
  await expect(goldSwitch(page, '3×4')).toBeChecked()
  await expect(page.getByTestId('available-frames-summary')).toHaveText(
    '3 frames available to participants',
  )
})

test('the theme editor and previews fit a phone screen', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await pairAndSignIn(page)
  await page.getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  await page.getByText('Advanced colors').click()
  // One preview only (no separate phone copy), and nothing wider than the phone.
  await expect(page.getByText('Phone width')).toHaveCount(0)
  await expect(page.getByTestId('preview-viewport')).toHaveCount(1)
  await expect(page.getByTestId('theme-option').first()).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
})

test('themes and built-in frames survive a backend restart @after-restart', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  await page.getByText('Advanced colors').click()
  await expect(page.getByLabel('Links hex value', { exact: true })).toHaveValue(LINK)
  await expect(goldSwitch(page, '4×6')).toBeChecked()
  await page.getByRole('button', { name: 'Frame selection' }).click()
  await expect
    .poll(
      () =>
        preview(page)
          .getByRole('list', { name: 'Frames' })
          .locator('img')
          .first()
          .evaluate((img: HTMLImageElement) => img.naturalWidth),
      { timeout: 20_000 },
    )
    .toBeGreaterThan(0)
})
