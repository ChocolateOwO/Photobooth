import { expect, test } from '@playwright/test'

import { pairAndSignIn } from './support/admin'

/**
 * Phase 10, as an organizer sees it after the guests of the earlier specs: History lists their
 * visits and tells one from start to finish, Statistics counts them, and the Activity log shows
 * what organizers did. Organizer tests (Admin "Test booth") never appear as guests' visits.
 */

test('History tells a finished visit from start to finish', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/history')
  await expect(page.getByRole('heading', { name: 'History' })).toBeVisible()
  await page.getByRole('button', { name: 'All time' }).click()
  await page.getByRole('button', { name: 'Photos made' }).click()
  const table = page.getByTestId('history-table')
  await expect(table).toBeVisible()
  const finished = table.getByRole('row').filter({ hasText: 'Finished' }).first()
  await expect(finished).toBeVisible()
  await finished.getByRole('button', { name: 'Details' }).click()
  const timeline = page.getByTestId('visit-dialog').getByTestId('visit-timeline')
  await expect(timeline.getByText('A guest started a visit')).toBeVisible()
  await expect(timeline.getByText(/Finished photos? made/)).toBeVisible()
  await expect(timeline.getByText(/Visit ended: Finished/)).toBeVisible()
})

test('Statistics counts the guests and the Activity log shows the organizers', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/statistics')
  await page.getByRole('button', { name: 'All time' }).click()
  const tiles = page.getByTestId('statistics-tiles')
  await expect(tiles).toBeVisible()
  const visits = Number(
    await tiles.getByText('Visits', { exact: true }).locator('xpath=following-sibling::p[1]').textContent(),
  )
  expect(visits).toBeGreaterThan(0)
  await expect(page.getByRole('region', { name: 'Visits by layout' }).getByText('2×6')).toBeVisible()

  await page.goto('/admin/activity')
  await page.getByRole('button', { name: 'Organizers' }).click()
  const log = page.getByTestId('activity-log')
  await expect(log.getByText('Signed in').first()).toBeVisible()
  await expect(log.getByText('Made an event profile live').first()).toBeVisible()
})
