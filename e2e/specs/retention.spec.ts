import { expect, test } from './support/fixtures'

import { PERSISTED, pairAndSignIn, profileRow } from './support/admin'

/**
 * Phase 11, as an organizer uses it: the retention policy, a cleanup that looks before it
 * deletes, and a deleted event deleted for good. Nothing in this fresh instance is past its time,
 * so the look finds nothing to delete and nothing is deleted.
 */

test('Retention shows the policies and a look deletes nothing', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/retention')
  await expect(page.getByRole('heading', { name: 'Retention', exact: true })).toBeVisible()
  const standard = page.getByTestId('retention-policy').filter({ hasText: 'Standard' })
  await expect(standard).toContainText('Default')
  await expect(standard).toContainText('Original photos 7 days · finished photos 30 days')
  const housekeeping = page.getByRole('form', { name: 'Booth housekeeping' })
  await expect(housekeeping.getByLabel(/Database backups/)).toHaveValue('7')
  await expect(housekeeping.getByRole('button', { name: 'Save housekeeping' })).toBeDisabled()

  await page.getByRole('button', { name: 'Check what would be deleted' }).click()
  await expect(page.getByTestId('retention-counts')).toBeVisible()
  await expect(page.getByText('Nothing is past its time.')).toBeVisible()
  await expect(page.getByTestId('retention-runs')).toContainText('(check only)')
  // The booth's own startup cleanup ran before it opened.
  await expect(page.getByTestId('retention-runs')).toContainText('When the booth started')
})

test('an event chooses its own retention policy (P11-9)', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/retention')
  await page.getByRole('button', { name: 'Add policy' }).click()
  const form = page.getByRole('form', { name: 'New retention policy' })
  await form.getByLabel('Name').fill('E2E Short')
  await form.getByLabel(/Original photos/).fill('2')
  await form.getByRole('button', { name: 'Add policy' }).click()
  const short = page.getByTestId('retention-policy').filter({ hasText: 'E2E Short' })
  await expect(short).toContainText('Original photos 2 days')
  await expect(short).toContainText('Used by 0 event profiles')

  await page.goto('/admin')
  await profileRow(page, PERSISTED.copy)
    .getByRole('link', { name: `Edit ${PERSISTED.copy}`, exact: true })
    .click()
  const choice = page.getByLabel('Retention policy')
  await expect(choice).toHaveValue('00000000-0000-4000-8000-000000000001') // Standard
  // The link beside it reads clearly on the dark panel and shows where the keyboard is.
  const manage = page.getByRole('link', { name: 'Manage policies' })
  await expect(manage).toHaveCSS('color', 'rgb(244, 246, 248)')
  await choice.focus()
  await page.keyboard.press('Tab')
  await expect(manage).toBeFocused()
  await expect(manage).toHaveCSS('outline-style', 'solid')
  await expect(manage).toHaveCSS('outline-width', '3px')
  await choice.selectOption({ label: 'E2E Short' })
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toBeVisible()
  await page.getByRole('button', { name: 'Close' }).click()

  await page.goto('/admin/retention')
  await expect(short).toContainText('Used by 1 event profile')
  await expect(short.getByRole('button', { name: 'Delete E2E Short' })).toHaveCount(0) // in use

  // Back to Standard so the later specs keep the defaults; the policy can then go.
  await page.goto('/admin')
  await profileRow(page, PERSISTED.copy)
    .getByRole('link', { name: `Edit ${PERSISTED.copy}`, exact: true })
    .click()
  await page.getByLabel('Retention policy').selectOption({ label: 'Standard (default)' })
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toBeVisible()
  await page.goto('/admin/retention')
  await short.getByRole('button', { name: 'Delete E2E Short' }).click()
  await expect(short).toHaveCount(0)

  // Every step is in the Admin Activity Log, by organizer, never with the policy's name.
  await page.goto('/admin/activity')
  await page.getByRole('button', { name: 'Organizers' }).click()
  const log = page.getByTestId('activity-log')
  await expect(log.getByText('Added a retention policy').first()).toBeVisible()
  await expect(log.getByText('Chose the retention policy of an event profile').first()).toBeVisible()
  await expect(log.getByText('Deleted a retention policy').first()).toBeVisible()
  await expect(log.getByText('E2E Short')).toHaveCount(0)
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
