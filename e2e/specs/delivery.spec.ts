import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { expect, test, type Browser, type Page } from '@playwright/test'

import { instanceRoot, PERSISTED, pairAndSignIn, profileRow } from './support/admin'

/**
 * Phase 8, as a guest lives it: the photos are taken, the booth makes the finished photos and
 * shows a QR code, and a phone on the same network opens it, saves a photo and downloads them
 * all. A phone is a separate browser with nothing of the booth's: no cookie, no pairing.
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

async function takePhotos(page: Page, size: string): Promise<void> {
  await page.goto('/booth/frames')
  await page.getByRole('tab', { name: size }).click()
  const slide = page.getByTestId('frame-slide').filter({ hasText: 'Midnight' }).first()
  await slide.scrollIntoViewIfNeeded()
  await slide.getByRole('button', { name: 'Use this frame' }).click()
  await page
    .getByRole('dialog', { name: 'Use this frame?' })
    .getByRole('button', { name: 'Start with this frame' })
    .click()
  await expect(page.getByRole('heading', { name: 'All photos taken' })).toBeVisible({
    timeout: 60_000,
  })
  await page.getByRole('button', { name: 'These are good' }).click()
  await expect(page).toHaveURL(/\/booth\/done$/)
  await expect(page.getByTestId('delivery-qr')).toBeVisible({ timeout: 30_000 })
}

async function phone(browser: Browser): Promise<{ page: Page; close: () => Promise<void> }> {
  const context = await browser.newContext({ acceptDownloads: true })
  return { page: await context.newPage(), close: () => context.close() }
}

async function visit(page: Page): Promise<{ id: string; state: string } | null> {
  return (await (await page.request.get('/api/booth/sessions/current')).json()) as never
}

test('a guest takes two strips home with a phone: the page, one photo and all of them', async ({
  page,
  browser,
}) => {
  test.setTimeout(120_000)
  await pairAndSignIn(page)
  await activate(page, QUICK)
  await takePhotos(page, '2×6')

  // The booth shows both strips and the link the QR code carries.
  await expect(page.getByTestId('finished-photos').getByRole('img')).toHaveCount(2)
  const url = (await page.getByTestId('delivery-url').textContent())?.trim() ?? ''
  expect(url).toMatch(/^http:\/\/127\.0\.0\.1:8114\/d\/[A-Za-z0-9_-]{43}$/)
  await expect(page.getByText(/same Wi-Fi as the booth/)).toBeVisible()
  // The QR code really is a picture (an image the browser could not decode is still "visible").
  await expect
    .poll(() => page.getByTestId('delivery-qr').evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
  await expect(page.getByText(/The link works until \d+ [A-Z][a-z]+ at \d\d:\d\d/)).toBeVisible()

  // A reload of the booth screen shows the very same link (the booth remembers it).
  await page.reload()
  await expect(page.getByTestId('delivery-url')).toHaveText(url)

  const guest = await phone(browser)
  try {
    const landing = await guest.page.goto(url)
    expect(landing?.status()).toBe(200)
    expect(landing?.headers()['referrer-policy']).toBe('no-referrer')
    await expect(guest.page.getByRole('heading', { name: 'Your photos' })).toBeVisible()
    await expect(guest.page.getByRole('img', { name: /Photo \d of 2/ })).toHaveCount(2)

    const saving = guest.page.waitForEvent('download')
    await guest.page.getByRole('link', { name: 'Save photo 1' }).click()
    const saved = await saving
    expect(saved.suggestedFilename()).toBe('photobooth-1.jpg')
    const bytes = readFileSync((await saved.path()) ?? '')
    expect(bytes.subarray(0, 2).toString('hex')).toBe('ffd8') // a JPEG

    const zipping = guest.page.waitForEvent('download')
    await guest.page.getByRole('link', { name: /Download all 2 photos/ }).click()
    const archive = await zipping
    expect(archive.suggestedFilename()).toBe('photobooth-photos.zip')
    const zipped = readFileSync((await archive.path()) ?? '')
    expect(zipped.subarray(0, 4).toString('hex')).toBe('504b0304') // a ZIP
    expect(zipped.includes(Buffer.from('photobooth-2.jpg'))).toBe(true)
  } finally {
    await guest.close()
  }

  // Done: the booth is ready for the next guest, and the first guest's link keeps working.
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(page).toHaveURL(/\/booth$/)
  expect(await visit(page)).toBeNull()
  const later = await phone(browser)
  try {
    expect((await later.page.goto(url))?.status()).toBe(200)
  } finally {
    await later.close()
  }

  // The token is the guest's key: it appears in no log file of the booth.
  const token = url.split('/d/')[1] ?? ''
  const logs = join(instanceRoot, 'data', 'logs')
  for (const name of readdirSync(logs)) {
    expect(readFileSync(join(logs, name), 'utf-8')).not.toContain(token)
  }
})

test('a phone gets nothing but its own photos from the delivery listener', async ({
  page,
  browser,
}) => {
  await pairAndSignIn(page)
  await takePhotos(page, '3×4')
  const url = (await page.getByTestId('delivery-url').textContent())?.trim() ?? ''
  const base = url.split('/d/')[0] ?? ''

  const guest = await phone(browser)
  try {
    for (const path of [
      '/d/' + 'A'.repeat(43), // well formed, nobody's
      '/d/' + url.split('/d/')[1] + '/files/00000000-0000-4000-8000-000000000000',
      '/api/health',
      '/api/booth/sessions/current',
      '/admin',
    ]) {
      const answer = await guest.page.request.get(base + path)
      expect(answer.status(), path).toBe(404)
      expect(await answer.text(), path).toBe('not found')
    }
  } finally {
    await guest.close()
  }
  await page.getByRole('button', { name: 'Done' }).click()
})

test('the event the later specs expect is active again', async ({ page }) => {
  await pairAndSignIn(page)
  await activate(page, PERSISTED.copy)
})
