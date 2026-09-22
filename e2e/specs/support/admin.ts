import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { expect, request, type Page } from '@playwright/test'

export const instanceRoot = process.env.PHOTOBOOTH_E2E_INSTANCE_ROOT ?? ''
export const adminPassword = process.env.PHOTOBOOTH_E2E_ADMIN_PASSWORD ?? ''
export const fixturesDir = process.env.PHOTOBOOTH_E2E_FIXTURES ?? ''
export const KIOSK_BASE = 'http://127.0.0.1:8112'

function runtimeSecret(name: string): string {
  return readFileSync(join(instanceRoot, 'config', 'runtime', name), 'utf-8')
}

/** Launcher-side pairing: rotate a code (launcher token) and open the pairing URL in `page`. */
export async function pairBrowser(page: Page): Promise<void> {
  const launcher = await request.newContext({
    baseURL: KIOSK_BASE,
    extraHTTPHeaders: { 'X-Photobooth-Launcher': runtimeSecret('launcher.token') },
  })
  try {
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const response = await launcher.post('/kiosk/pairing-code/rotate')
      if (response.status() === 204) {
        const code = runtimeSecret('pairing.code')
        await page.goto(`/kiosk/pair?code=${encodeURIComponent(code)}`)
        await expect(page).toHaveURL(/\/$/)
        return
      }
      expect(response.status()).toBe(429) // rotation is rate limited to 1/s
      await new Promise((resolve) => setTimeout(resolve, 1100))
    }
  } finally {
    await launcher.dispose()
  }
  throw new Error('could not pair the browser')
}

export async function signIn(page: Page, password = adminPassword): Promise<void> {
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: 'Admin sign in' })).toBeVisible()
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

export async function pairAndSignIn(page: Page): Promise<void> {
  expect(instanceRoot, 'run scripts\\e2e.ps1').not.toBe('')
  expect(adminPassword).not.toBe('')
  await pairBrowser(page)
  await signIn(page)
  await expect(page.getByText('Signed in as admin')).toBeVisible()
}

export function profileRow(page: Page, name: string) {
  return page
    .getByTestId('profile-row')
    .filter({ has: page.getByText(name, { exact: true }) })
}

export const PERSISTED = {
  original: 'E2E Wedding',
  copy: 'E2E Wedding (copy)',
  title: 'Welcome to our wedding',
  subtitle: 'Tap start and smile',
  startText: 'Let us go',
  primary: '#F2C94C',
} as const
