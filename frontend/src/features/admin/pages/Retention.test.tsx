import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

/**
 * Phase 11 in Admin: the retention policy, a cleanup that looks before it deletes and deletes
 * only behind a ticked confirmation, and deleting a deleted event for good.
 */

function signedIn(): FakeAdminServer {
  const server = new FakeAdminServer()
  server.signedIn = true
  return server
}

describe('Retention', () => {
  it('saves a changed policy and says what the server refuses', async () => {
    const server = signedIn()
    renderAdmin('/admin/retention', { server })
    const form = await screen.findByRole('form', { name: 'Retention policy' })
    const save = within(form).getByRole('button', { name: 'Save policy' })
    expect(save).toBeDisabled() // nothing changed yet

    const link = within(form).getByLabelText(/Take-home link works for/)
    await userEvent.clear(link)
    await userEvent.type(link, '40')
    await userEvent.click(save)
    expect(await within(form).findByRole('alert')).toHaveTextContent('can not outlive')

    await userEvent.clear(link)
    await userEvent.type(link, '3')
    await userEvent.click(within(form).getByRole('button', { name: 'Save policy' }))
    await waitFor(() => expect(server.retentionPolicy.revision).toBe(2))
    expect(server.retentionPolicy.link_days).toBe(3)
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
    expect(server.retentionRequests.at(-1)).toEqual({ dry_run: false, confirm: 'DELETE' })
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
    server.retentionCounts = [{ category: 'originals', items: 0, bytes: 0 }]
    renderAdmin('/admin/retention', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Check what would be deleted' }))
    expect(await screen.findByText('Nothing is past its time.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete these now' })).not.toBeInTheDocument()
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
