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
  await expect(view.getByRole('group', { name: 'Kiosk screen preview' })).toHaveCSS(
    'background-color',
    rgb(tokens.background ?? ''),
  )
  await expect(view.getByRole('button', { name: 'Back' })).toHaveCSS(
    'background-color',
    rgb(tokens.secondary_bg ?? ''),
  )
  await expect(view.getByRole('button', { name: 'Print' })).toHaveCSS(
    'background-color',
    rgb(tokens.primary_disabled_bg ?? ''),
  )
  await expect(view.getByText('Paper is running low.')).toHaveCSS('color', rgb(tokens.warning_text ?? ''))
  await expect(view.getByLabel('Email for your photos')).toHaveCSS(
    'background-color',
    rgb(tokens.input_bg ?? ''),
  )
}

test('built-in frames are there on a fresh setup and are read-only', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  for (const layout of LAYOUT_NAMES) {
    const list = page.getByRole('list', { name: `Built-in frames for ${layout}` })
    const cards = list.getByTestId('frame-card')
    await expect(cards).toHaveCount(FAMILIES.length)
    for (const family of FAMILIES) {
      const card = cards.filter({ has: page.getByRole('heading', { name: family, exact: true }) })
      await expect(card.getByText('Built-in', { exact: true })).toBeVisible()
      await expect(card.getByRole('button', { name: /Replace|Rename|Delete/ })).toHaveCount(0)
      await card.scrollIntoViewIfNeeded()
      await expect
        .poll(
          () =>
            card
              .getByRole('img', { name: `${family} sample output` })
              .evaluate((img: HTMLImageElement) => img.naturalWidth),
          { timeout: 20_000 },
        )
        .toBeGreaterThan(0)
    }
  }
  // All nine packaged frames (three families x three layouts) are listed by the API.
  const frames = (await (await page.request.get('/api/admin/frames')).json()) as { builtin: boolean }[]
  expect(frames.filter((f) => f.builtin)).toHaveLength(9)
})

test('a new profile starts with an accessible preset and built-in frames', async ({ page }) => {
  await pairAndSignIn(page)
  const themes = await catalog(page)
  expect(themes.presets.length).toBeGreaterThanOrEqual(6)
  const fallback = themes.presets.find((p) => p.id === themes.default_preset)
  await page.getByRole('link', { name: 'New profile' }).click()
  await expect(page.getByRole('radio', { name: new RegExp(`^${fallback?.name ?? ''}`) })).toBeChecked()
  await expect(page.getByTestId('contrast-ok')).toBeVisible()
  await expect(
    page.getByLabel('Frame for 3x4 print', { exact: true }).locator('option:checked'),
  ).toHaveText('Midnight (Built-in)') // the first layout starts with the default frame
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
  for (const layout of LAYOUT_NAMES) {
    const box = page.getByRole('checkbox', { name: layout, exact: true })
    if (!(await box.isChecked())) await box.check()
  }

  // Quick theme: the whole preset, not two colours.
  await page.getByRole('radio', { name: /^Celebration Gold/ }).check()
  await expectPreviewTokens(page, gold?.tokens ?? {})

  // A light background gives a light page with dark text; a dark one the opposite.
  await page.getByLabel('Background image').setInputFiles(join(fixturesDir, 'bg_light.jpg'))
  await expect(page.getByText('Colors extracted from background')).toBeVisible()
  const swatches = page.getByRole('list', { name: 'Colours found in the background' })
  await expect(swatches.getByRole('listitem').first()).toBeVisible()
  const lightSwatches = await swatches.innerText()
  const heading = preview(page).getByRole('heading', { name: 'Theme party' })
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

  // Built-in Celebration Gold frames to match, and save.
  for (const layout of LAYOUT_NAMES) {
    await page.getByLabel(`Frame for ${layout}`, { exact: true }).selectOption({ label: 'Celebration Gold (Built-in)' })
  }
  await expect(preview(page).getByText('Celebration Gold · Built-in')).toBeVisible()
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)

  await page.reload()
  await page.getByText('Advanced colors').click()
  await expect(page.getByLabel('Links hex value', { exact: true })).toHaveValue(LINK)
  await expect(page.getByLabel('Frame for 2x6 photo strip', { exact: true }).locator('option:checked')).toHaveText(
    'Celebration Gold (Built-in)',
  )
})

test('duplicating a profile keeps its theme and frames', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('button', { name: `Duplicate ${PROFILE}`, exact: true }).click()
  await expect(profileRow(page, COPY)).toBeVisible()
  await page.getByRole('link', { name: `Edit ${COPY}`, exact: true }).click()
  await page.getByText('Advanced colors').click()
  await expect(page.getByLabel('Links hex value', { exact: true })).toHaveValue(LINK)
  await expect(page.getByLabel('Frame for 3x4 print', { exact: true }).locator('option:checked')).toHaveText(
    'Celebration Gold (Built-in)',
  )
})

test('the theme editor and previews fit a phone screen', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await pairAndSignIn(page)
  await page.getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  await page.getByText('Advanced colors').click()
  await expect(page.getByTestId('event-preview-phone')).toBeVisible()
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
  await expect(preview(page).getByText('Celebration Gold · Built-in')).toBeVisible()
  await expect
    .poll(
      () =>
        preview(page)
          .getByRole('img', { name: /with Celebration Gold$/ })
          .evaluate((img: HTMLImageElement) => img.naturalWidth),
      { timeout: 20_000 },
    )
    .toBeGreaterThan(0)
})
