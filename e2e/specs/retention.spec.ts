import { expect, test } from '@playwright/test'

import { PERSISTED, pairAndSignIn, profileRow } from './support/admin'

/**
 * Phase 11, as an organizer uses it: the retention policy, a cleanup that looks before it
 * deletes, and a deleted event deleted for good. Nothing in this fresh instance is past its time,
 * so the look finds nothing to delete and nothing is deleted.
 */

test('Retention shows the policy and a look deletes nothing', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/retention')
  await expect(page.getByRole('heading', { name: 'Retention' })).toBeVisible()
  const form = page.getByRole('form', { name: 'Retention policy' })
  await expect(form.getByLabel(/Original photos/)).toHaveValue('7')
  await expect(form.getByLabel(/Finished photos/)).toHaveValue('30')
  await expect(form.getByRole('button', { name: 'Save policy' })).toBeDisabled()

  await page.getByRole('button', { name: 'Check what would be deleted' }).click()
  await expect(page.getByTestId('retention-counts')).toBeVisible()
  await expect(page.getByText('Nothing is past its time.')).toBeVisible()
  await expect(page.getByTestId('retention-runs')).toContainText('(check only)')
  // The booth's own startup cleanup ran before it opened.
  await expect(page.getByTestId('retention-runs')).toContainText('When the booth started')
})

test('a deleted event can be deleted for good', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin')
  await page.getByRole('button', { name: `Duplicate ${PERSISTED.copy}`, exact: true }).click()
  const copy = `${PERSISTED.copy} (copy)`
  await expect(profileRow(page, copy)).toBeVisible()
  await page.getByRole('button', { name: `Delete ${copy}`, exact: true }).click()
  await page
    .getByRole('alertdialog', { name: `Delete ${copy}?` })
    .getByRole('button', { name: 'Delete profile' })
    .click()
  await expect(profileRow(page, copy)).toHaveCount(0)

  await page.getByRole('checkbox', { name: 'Show deleted profiles' }).check()
  await page.getByRole('button', { name: `Delete ${copy} for good`, exact: true }).click()
  const dialog = page.getByTestId('remove-event')
  await expect(dialog.getByText(/its 0 visits/)).toBeVisible()
  const go = dialog.getByRole('button', { name: 'Delete for good' })
  await expect(go).toBeDisabled()
  await dialog.getByRole('checkbox').check()
  await go.click()
  await expect(profileRow(page, copy)).toHaveCount(0) // gone, even among the deleted ones
  await expect(profileRow(page, PERSISTED.copy)).toBeVisible() // nothing else touched
})
