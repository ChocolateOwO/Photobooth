import { join } from 'node:path'

import { expect, request, test } from './support/fixtures'

import {
  fixturesDir,
  KIOSK_BASE,
  pairAndSignIn,
  pairBrowser,
  PERSISTED,
  profileRow,
  signIn,
} from './support/admin'

// Specs in this file share one e2e instance and build on each other's data.
test.describe.configure({ mode: 'serial' })

test('unpaired and signed-out browsers get no admin access', async ({ browser }) => {
  const context = await browser.newContext({ baseURL: 'http://127.0.0.1:5192' })
  const page = await context.newPage()
  try {
    await page.goto('/admin')
    await expect(page.getByRole('heading', { name: 'Kiosk not paired' })).toBeVisible()
    expect((await page.request.get('/api/admin/profiles')).status()).toBe(401)
    expect((await page.request.post('/api/admin/auth/login', { data: {} })).status()).toBe(401)

    await pairBrowser(page)
    await page.goto('/admin')
    await expect(page.getByRole('heading', { name: 'Admin sign in' })).toBeVisible()
    // Paired device but no admin session: reads and writes are refused by the server.
    expect((await page.request.get('/api/admin/profiles')).status()).toBe(401)
    const key = await page.evaluate(() => window.localStorage.getItem('photobooth.deviceKey.dummy'))
    const status = await page.evaluate(async (deviceKey) => {
      const response = await fetch('/api/admin/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Photobooth-Device-Key': deviceKey ?? '' },
        body: '{}',
      })
      return response.status
    }, key)
    expect(status).toBe(401)

    // Direct API access from outside the browser (no cookies at all) is refused as well.
    const outsider = await request.newContext({ baseURL: KIOSK_BASE })
    try {
      expect((await outsider.get('/api/admin/profiles')).status()).toBe(401)
      expect((await outsider.post('/api/admin/assets')).status()).toBe(401)
    } finally {
      await outsider.dispose()
    }

    await signIn(page, 'definitely-not-the-password')
    await expect(page.getByRole('alert')).toHaveText('Wrong username or password.')
    await expect(page.getByLabel('Password')).toHaveValue('')
  } finally {
    await context.close()
  }
})

test('create a profile with uploads, live preview and saved settings', async ({ page }) => {
  await pairAndSignIn(page)
  await expect(page.getByRole('heading', { name: 'Event Profiles' })).toBeVisible()
  await page.getByRole('link', { name: 'New profile' }).click()
  await expect(page.getByRole('heading', { name: 'New Event Profile' })).toBeVisible()

  // Grey example text is a real placeholder, readable, and gone once the field has a value.
  const nameField = page.getByLabel('Profile name')
  await expect(nameField).toHaveAttribute('placeholder', 'e.g. Chiang Mai Expo 2026')
  await expect(nameField).toHaveValue('')
  const placeholderColor = await nameField.evaluate(
    (el) => getComputedStyle(el, '::placeholder').color,
  )
  expect(placeholderColor).toBe('rgb(169, 180, 191)') // --pb-color-muted
  expect(await nameField.evaluate((el) => el.matches(':placeholder-shown'))).toBe(true)

  await page.getByLabel('Profile name').fill(PERSISTED.original)
  expect(await nameField.evaluate((el) => el.matches(':placeholder-shown'))).toBe(false)
  await expect(page.getByText('Only admins see this name. It helps you find the profile later.')).toBeVisible()
  await page.getByLabel('Title', { exact: true }).fill(PERSISTED.title)
  await page.getByLabel('Subtitle').fill(PERSISTED.subtitle)
  await page.getByLabel('Start button text').fill(PERSISTED.startText)
  await page.getByRole('checkbox', { name: 'Mirror the camera preview' }).uncheck()
  await page.getByLabel('Inactivity timeout (seconds)').fill('240')
  await page.getByRole('radio', { name: 'Retake all photos' }).check()

  const preview = page.getByTestId('event-preview')
  // The start screen shows the Start button, never the title or subtitle.
  await expect(preview.getByRole('button', { name: PERSISTED.startText })).toBeVisible()
  await expect(preview.getByText(PERSISTED.title)).toHaveCount(0)
  await expect(page.getByTestId('preparation-preview').getByText('Mirror: off')).toBeVisible()

  await page.getByLabel('Logo image').setInputFiles(join(fixturesDir, 'logo.png'))
  await expect(page.getByRole('img', { name: 'Logo preview' })).toBeVisible()
  await expect(page.getByText('256 × 128 px')).toBeVisible()
  await page.getByLabel('Background image').setInputFiles(join(fixturesDir, 'background.jpg'))
  await expect(page.getByRole('img', { name: 'Background preview' })).toBeVisible()
  await expect(page.getByText('1280 × 720 px')).toBeVisible()
  // The uploaded image really loads from the server (admin cookie on a plain <img>).
  await expect
    .poll(() => preview.getByRole('img', { name: 'Event logo' }).evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBe(256)

  // Invalid upload is refused before it reaches the server.
  await page.getByLabel('Logo image').setInputFiles({
    name: 'drawing.svg',
    mimeType: 'image/svg+xml',
    buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'),
  })
  const refused = page.getByRole('alertdialog', { name: 'The logo was not uploaded' })
  await expect(refused).toContainText('Logo must be a PNG or JPEG image.')
  await refused.getByRole('button', { name: 'Close' }).click()

  // The background proposed its own colours; then one colour is changed by hand.
  await expect(page.getByText('Colors extracted from background')).toBeVisible()
  // Main colours: only Button and Text are edited; the related shades are regenerated.
  await page.getByLabel('Button colour', { exact: true }).fill(PERSISTED.primary.toLowerCase())
  await expect(preview.getByRole('button', { name: PERSISTED.startText })).toHaveCSS(
    'background-color',
    'rgb(242, 201, 76)',
  )

  const save = page.getByRole('button', { name: 'Save profile' })
  expect((await save.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(64)
  expect((await page.getByLabel('Title', { exact: true }).boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(64)
  await save.click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name: 'Edit Event Profile' })).toBeVisible()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toContainText('Profile saved successfully.')

  await page.reload()
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(PERSISTED.title)
  await expect(page.getByLabel('Button colour', { exact: true })).toHaveValue(PERSISTED.primary.toLowerCase())
  await expect(page.getByRole('radio', { name: 'Retake all photos' })).toBeChecked()
  await expect(page.getByRole('img', { name: 'Logo preview' })).toBeVisible()
})

test('duplicate, activate, soft delete and restore', async ({ page }) => {
  await pairAndSignIn(page)
  await expect(profileRow(page, PERSISTED.original)).toBeVisible()

  await page.getByRole('button', { name: `Duplicate ${PERSISTED.original}`, exact: true }).click()
  await expect(profileRow(page, PERSISTED.copy)).toBeVisible()

  await page.getByRole('button', { name: `Activate ${PERSISTED.copy}`, exact: true }).click()
  await expect(page.getByRole('status')).toHaveText(`${PERSISTED.copy} is now the active profile.`)
  await expect(profileRow(page, PERSISTED.copy).getByText('Active', { exact: true })).toBeVisible()
  await expect(profileRow(page, PERSISTED.original).getByText('Active', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: `Delete ${PERSISTED.copy}`, exact: true })).toBeDisabled()

  await page.getByRole('button', { name: `Delete ${PERSISTED.original}`, exact: true }).click()
  const dialog = page.getByRole('alertdialog', { name: `Delete ${PERSISTED.original}?` })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete profile' }).click()
  await expect(profileRow(page, PERSISTED.original)).toHaveCount(0)

  await page.getByRole('checkbox', { name: 'Show deleted profiles' }).check()
  await expect(profileRow(page, PERSISTED.original).getByText('Deleted', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: `Restore ${PERSISTED.original}`, exact: true }).click()
  await expect(profileRow(page, PERSISTED.original).getByText('Deleted', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('link', { name: `Edit ${PERSISTED.original}`, exact: true })).toBeVisible()
})

test('a stale edit is refused and can be reloaded', async ({ page, context }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: `Edit ${PERSISTED.original}`, exact: true }).click()
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(PERSISTED.title)

  const other = await context.newPage() // second tab, same signed-in browser
  await other.goto(page.url())
  await other.getByLabel('Subtitle').fill('Changed in the other tab')
  await other.getByRole('button', { name: 'Save profile' }).click()
  await expect(other.getByRole('alertdialog', { name: 'Saved' })).toBeVisible()
  await other.close()

  await page.getByLabel('Subtitle').fill('My older edit')
  await page.getByRole('button', { name: 'Save profile' }).click()
  const conflict = page.getByRole('alertdialog', { name: 'Changed somewhere else' })
  await expect(conflict).toContainText('This profile was changed somewhere else. Reload to get the latest version.')
  await conflict.getByRole('button', { name: 'Reload latest' }).click()
  await expect(conflict).toHaveCount(0)
  await expect(page.getByLabel('Subtitle')).toHaveValue('Changed in the other tab')
  await page.getByLabel('Subtitle').fill(PERSISTED.subtitle)
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toContainText('Profile saved successfully.')
})

test('an expired admin session returns to sign-in without showing data', async ({ page, context }) => {
  await pairAndSignIn(page)
  await expect(profileRow(page, PERSISTED.original)).toBeVisible()

  // The server-side session is gone (idle/absolute expiry, logout elsewhere or restart).
  await context.clearCookies({ name: 'pb_admin_dummy' })
  // click, not check: the refused request replaces the page with sign-in, so the box may never be
  // seen checked (check() then waited for it and timed out when the answer came back quickly).
  await page.getByRole('checkbox', { name: 'Show deleted profiles' }).click()
  await expect(page.getByRole('alert')).toHaveText('Your session expired. Sign in again.')
  await expect(page.getByRole('heading', { name: 'Admin sign in' })).toBeVisible()
  await expect(profileRow(page, PERSISTED.original)).toHaveCount(0)

  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill(process.env.PHOTOBOOTH_E2E_ADMIN_PASSWORD ?? '')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(profileRow(page, PERSISTED.original)).toBeVisible()

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('heading', { name: 'Admin sign in' })).toBeVisible()
  expect((await page.request.get('/api/admin/profiles')).status()).toBe(401)
})

test('saved profiles reopen and stay editable after a backend restart @after-restart', async ({ page }) => {
  await pairAndSignIn(page) // device pairing and admin sessions never survive a restart
  await expect(profileRow(page, PERSISTED.original)).toBeVisible()
  await expect(profileRow(page, PERSISTED.copy).getByText('Active', { exact: true })).toBeVisible()

  await page.getByRole('link', { name: `Edit ${PERSISTED.original}`, exact: true }).click()
  await expect(page.getByLabel('Profile name')).toHaveValue(PERSISTED.original)
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(PERSISTED.title)
  await expect(page.getByLabel('Subtitle')).toHaveValue(PERSISTED.subtitle)
  await expect(page.getByLabel('Start button text')).toHaveValue(PERSISTED.startText)
  await expect(page.getByLabel('Button colour', { exact: true })).toHaveValue(PERSISTED.primary.toLowerCase())
  await expect(page.getByLabel('Inactivity timeout (seconds)')).toHaveValue('240')
  await expect(page.getByRole('checkbox', { name: 'Mirror the camera preview' })).not.toBeChecked()
  await expect(page.getByRole('radio', { name: 'Retake all photos' })).toBeChecked()
  await expect
    .poll(() =>
      page.getByRole('img', { name: 'Background preview' }).evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBe(1280)

  await page.getByLabel('Title', { exact: true }).fill('Edited after restart')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toContainText('Profile saved successfully.')
  await page.reload()
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Edited after restart')
})
