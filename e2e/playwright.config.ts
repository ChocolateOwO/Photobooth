import { defineConfig, devices } from '@playwright/test'

/**
 * E2E runs against a throwaway instance created by scripts\e2e.ps1 (never Dummy data):
 *   kiosk API 127.0.0.1:8112, delivery 127.0.0.1:8114, built UI via vite preview 127.0.0.1:5192.
 */
const envFile = required('PHOTOBOOTH_E2E_ENV_FILE')
const python = required('PHOTOBOOTH_E2E_PYTHON')
const frontendDir = required('PHOTOBOOTH_E2E_FRONTEND_DIR')
const instanceRoot = required('PHOTOBOOTH_E2E_INSTANCE_ROOT')
// Browsers must come from the isolated Dummy runtime store, never the shared user cache.
const browsersPath = required('PLAYWRIGHT_BROWSERS_PATH')
if (!/[\\/]Dummy[\\/]data[\\/]playwright-browsers$/i.test(browsersPath)) {
  throw new Error(
    `PLAYWRIGHT_BROWSERS_PATH must be Dummy\\data\\playwright-browsers, got ${browsersPath}`,
  )
}

function required(name: string): string {
  const value = process.env[name]
  if (!value) {
    throw new Error(`${name} is not set; run scripts\\e2e.ps1`)
  }
  return value
}

export default defineConfig({
  testDir: './specs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 60_000,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5192',
    trace: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `"${python}" -m photobooth serve --env-file "${envFile}" --expect-root "${instanceRoot}" --expect-profile e2e`,
      url: 'http://127.0.0.1:8112/api/health',
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm run preview',
      cwd: frontendDir,
      url: 'http://127.0.0.1:5192/',
      env: { PHOTOBOOTH_KIOSK_PORT: '8112', PHOTOBOOTH_INSTANCE: 'dummy' },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
