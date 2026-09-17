import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

function signedInServer() {
  const server = new FakeAdminServer()
  server.signedIn = true
  return server
}

function row(name: string): HTMLElement {
  const match = screen
    .getAllByTestId('profile-row')
    .find((element) => within(element).queryByText(name, { exact: true }) !== null)
  if (!match) throw new Error(`no row for ${name}`)
  return match
}

describe('ProfileListPage', () => {
  it('shows an empty state', async () => {
    renderAdmin('/admin', { server: signedInServer() })
    expect(await screen.findByText('No event profiles yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New profile' })).toHaveAttribute('href', '/admin/profiles/new')
  })

  it('activates a profile and marks only that one active', async () => {
    const server = signedInServer()
    server.seedProfile({ name: 'Wedding' }, { is_active: true })
    server.seedProfile({ name: 'Gala' })
    renderAdmin('/admin', { server })

    await userEvent.click(await screen.findByRole('button', { name: 'Activate Gala' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Gala is now the active profile.')
    await waitFor(() => expect(within(row('Gala')).getByText('Active')).toBeInTheDocument())
    expect(within(row('Wedding')).queryByText('Active')).toBeNull()
    expect(screen.getByRole('button', { name: 'Delete Gala' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Delete Wedding' })).toBeEnabled()
  })

  it('duplicates a profile', async () => {
    const server = signedInServer()
    server.seedProfile({ name: 'Wedding' })
    renderAdmin('/admin', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Duplicate Wedding' }))
    expect(await screen.findByText('Wedding (copy)')).toBeInTheDocument()
    expect(server.profiles.size).toBe(2)
  })

  it('soft-deletes after confirmation and restores from the deleted view', async () => {
    const server = signedInServer()
    const party = server.seedProfile({ name: 'Party' })
    renderAdmin('/admin', { server })

    await userEvent.click(await screen.findByRole('button', { name: 'Delete Party' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: 'Delete Party?' })).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(server.profiles.get(party.id)?.deleted_at).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Delete Party' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete profile' }))
    expect(await screen.findByText('No event profiles yet.')).toBeInTheDocument()
    const deleteRequest = server.requests.find((r) => r.method === 'DELETE')
    expect(deleteRequest?.path).toBe(`/api/admin/profiles/${party.id}?revision=1`)

    await userEvent.click(screen.getByRole('checkbox', { name: 'Show deleted profiles' }))
    expect(await screen.findByText('Deleted')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit Party' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Restore Party' }))
    await waitFor(() => expect(screen.queryByText('Deleted')).toBeNull())
    expect(screen.getByRole('link', { name: 'Edit Party' })).toBeInTheDocument()
  })

  it('shows the server reason when a mutation is refused', async () => {
    const server = signedInServer()
    const party = server.seedProfile({ name: 'Party' })
    renderAdmin('/admin', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Party' }))
    // Another admin tab activated it meanwhile: the server refuses with its own reason.
    const current = server.profiles.get(party.id)
    if (!current) throw new Error('missing profile')
    server.profiles.set(party.id, { ...current, is_active: true })
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete profile' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('the active profile can not be deleted')
  })
})
