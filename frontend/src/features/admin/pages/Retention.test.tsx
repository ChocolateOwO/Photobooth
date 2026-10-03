import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

/**
 * Phase 11 in Admin: the retention policies (one per event, P11-9) and the booth's housekeeping, a cleanup that looks before it deletes and deletes
 * only behind a ticked confirmation, and deleting a deleted event for good.
 */

function signedIn(): FakeAdminServer {
  const server = new FakeAdminServer()
  server.signedIn = true
  return server
}

describe('Retention', () => {
  it('lists the policies with their default and use, and saves a changed one', async () => {
    const server = signedIn()
    renderAdmin('/admin/retention', { server })
    const list = await screen.findByTestId('retention-policies')
    const standard = within(list).getByTestId('retention-policy')
    expect(standard).toHaveTextContent('Standard')
    expect(standard).toHaveTextContent('Default')
    expect(standard).toHaveTextContent('Original photos 7 days · finished photos 30 days · link 7 days')
    expect(standard).toHaveTextContent('Used by 1 event profile')
    // The default (and any policy in use) can not be deleted from here.
    expect(within(standard).queryByRole('button', { name: 'Delete Standard' })).toBeNull()

    await userEvent.click(within(standard).getByRole('button', { name: 'Edit Standard' }))
    const form = await screen.findByRole('form', { name: 'Edit Standard' })
    expect(form).toHaveTextContent('Visits already made keep the deadlines they started with.')
    const link = within(form).getByLabelText(/Take-home link works for/)
    await userEvent.clear(link)
    await userEvent.type(link, '40')
    await userEvent.click(within(form).getByRole('button', { name: 'Save policy' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent('can not outlive')

    await userEvent.clear(link)
    await userEvent.type(link, '3')
    await userEvent.click(within(form).getByRole('button', { name: 'Save policy' }))
    await waitFor(() => expect(server.retentionPolicies[0]?.revision).toBe(2))
    expect(server.retentionPolicies[0]?.link_days).toBe(3)
    await waitFor(() => expect(screen.queryByRole('form', { name: 'Edit Standard' })).toBeNull())
  })

  it('adds a policy, makes it the default, and deletes an unused one', async () => {
    const server = signedIn()
    renderAdmin('/admin/retention', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Add policy' }))
    const form = await screen.findByRole('form', { name: 'New retention policy' })
    await userEvent.type(within(form).getByLabelText('Name'), 'Short')
    const originals = within(form).getByLabelText(/Original photos/)
    await userEvent.clear(originals)
    await userEvent.type(originals, '2')
    await userEvent.click(within(form).getByRole('button', { name: 'Add policy' }))
    await waitFor(() => expect(server.retentionPolicies.map((p) => p.name)).toEqual(['Standard', 'Short']))
    expect(server.retentionPolicies[1]?.originals_days).toBe(2)

    await userEvent.click(await screen.findByRole('button', { name: 'Make Short the default' }))
    await waitFor(() => expect(server.retentionPolicies[1]?.is_default).toBe(true))
    expect(server.retentionPolicies[0]?.is_default).toBe(false)
  })

  it('deletes a policy no event profile uses', async () => {
    const server = signedIn()
    const [standard] = server.retentionPolicies
    if (!standard) throw new Error('the fake server starts with the Standard policy')
    server.retentionPolicies = [
      standard,
      { ...standard, id: 'spare', name: 'Spare', is_default: false, used_by: 0 },
    ]
    renderAdmin('/admin/retention', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Spare' }))
    await waitFor(() => expect(server.retentionPolicies.map((p) => p.name)).toEqual(['Standard']))
  })
  it('saves the booth housekeeping on its own', async () => {
    const server = signedIn()
    renderAdmin('/admin/retention', { server })
    const form = await screen.findByRole('form', { name: 'Booth housekeeping' })
    const save = within(form).getByRole('button', { name: 'Save housekeeping' })
    expect(save).toBeDisabled()
    const backups = within(form).getByLabelText(/Database backups/)
    await userEvent.clear(backups)
    await userEvent.type(backups, '3')
    await userEvent.click(save)
    await waitFor(() => expect(server.housekeeping.revision).toBe(3))
    expect(server.housekeeping.backup_days).toBe(3)
  })
  it('looks first, and deletes only after the box is ticked', async () => {
    const server = signedIn()
    renderAdmin('/admin/retention', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Check what would be deleted' }))
    const counts = await screen.findByTestId('retention-counts')
    expect(within(counts).getByText('Original photos')).toBeInTheDocument()
    expect(within(counts).getByText('4')).toBeInTheDocument()
    expect(within(counts).getByText('4.0 MB')).toBeInTheDocument()
    expect(server.retentionRequests).toEqual([{ dry_run: true }]) // a look deletes nothing

    await userEvent.click(screen.getByRole('button', { name: 'Delete these now' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete permanently?' })
    const go = within(dialog).getByRole('button', { name: 'Delete permanently' })
    expect(go).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('checkbox'))
    await userEvent.click(go)
    expect(await screen.findByRole('status')).toHaveTextContent('Deleted 4 items.')
    expect(server.retentionRequests.at(-1)).toEqual({
      dry_run: false,
      confirm: 'DELETE',
      housekeeping_revision: 2,
    })
    expect(await screen.findByTestId('retention-runs')).toHaveTextContent('By hand')
  })

  it('"Keep everything" deletes nothing', async () => {
    const server = signedIn()
    renderAdmin('/admin/retention', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Check what would be deleted' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete these now' }))
    await userEvent.click(screen.getByRole('button', { name: 'Keep everything' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(server.retentionRequests).toEqual([{ dry_run: true }])
  })

  it('says when nothing is past its time', async () => {
    const server = signedIn()
    server.retentionCounts = [{ category: 'originals', items: 0, bytes: 0, failed: 0 }]
    renderAdmin('/admin/retention', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Check what would be deleted' }))
    expect(await screen.findByText('Nothing is past its time.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete these now' })).not.toBeInTheDocument()
  })
})

describe('Retention after the inspection (P11-008, P11-009)', () => {
  it('an incomplete check offers no deletion and says what could not be checked', async () => {
    const server = signedIn()
    server.retentionCounts = [{ category: 'originals', items: 0, bytes: 0, failed: 0 }]
    server.retentionErrors = ['outputs: OperationalError']
    renderAdmin('/admin/retention', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Check what would be deleted' }))
    expect(await screen.findByText(/Some things could not be checked: outputs/)).toBeInTheDocument()
    expect(screen.queryByText('Nothing is past its time.')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete these now' })).not.toBeInTheDocument()
  })

  it('housekeeping changed after the check is refused, and the check is dropped', async () => {
    const server = signedIn()
    renderAdmin('/admin/retention', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Check what would be deleted' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete these now' }))
    server.housekeeping = { ...server.housekeeping, revision: 9 } // changed elsewhere
    const dialog = screen.getByRole('dialog', { name: 'Delete permanently?' })
    await userEvent.click(within(dialog).getByRole('checkbox'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete permanently' }))
    expect(await screen.findByText(/The housekeeping settings changed since the check/)).toBeInTheDocument()
    expect(screen.queryByTestId('retention-counts')).not.toBeInTheDocument()
  })
})
describe('Deleting an event for good', () => {
  it('counts its visits first and needs the box ticked', async () => {
    const server = signedIn()
    const profile = server.seedProfile({ name: 'Old Party' }, { deleted_at: '2026-09-30T10:00:00Z' })
    server.eventVisits.set(profile.id, 3)
    renderAdmin('/admin', { server })

    await userEvent.click(await screen.findByLabelText('Show deleted profiles'))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Old Party for good' }))
    const dialog = await screen.findByTestId('remove-event')
    expect(await within(dialog).findByText(/its 3 visits/)).toBeInTheDocument()
    const go = within(dialog).getByRole('button', { name: 'Delete for good' })
    expect(go).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('checkbox'))
    await userEvent.click(go)
    await waitFor(() =>
      expect(server.eventRemovals.map((r) => r.body)).toEqual([
        { dry_run: true },
        { dry_run: false, confirm: 'DELETE' },
      ]),
    )
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Delete Old Party for good' })).toBeNull(),
    )
  })
})
