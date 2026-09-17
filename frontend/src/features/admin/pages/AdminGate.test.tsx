import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

async function signIn(password = 'correct horse battery staple') {
  const username = await screen.findByLabelText('Username')
  await userEvent.clear(username)
  await userEvent.type(username, 'admin')
  await userEvent.type(screen.getByLabelText('Password'), password)
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('AdminGate', () => {
  it('asks to pair the kiosk when this browser has no device key', async () => {
    const { server } = renderAdmin('/admin', { paired: false })
    expect(await screen.findByRole('heading', { name: 'Kiosk not paired' })).toBeInTheDocument()
    expect(screen.getByText(/run scripts\\run-dummy\.ps1 -PairOnly/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(server.requests.filter((r) => r.path.startsWith('/api/admin'))).toEqual([])
  })

  it('shows the sign-in form and no admin data while signed out', async () => {
    const server = new FakeAdminServer()
    server.seedProfile({ name: 'Secret gala' })
    renderAdmin('/admin', { server })
    expect(await screen.findByRole('heading', { name: 'Admin sign in' })).toBeInTheDocument()
    expect(screen.queryByText('Secret gala')).not.toBeInTheDocument()
    expect(server.requests.some((r) => r.path.startsWith('/api/admin/profiles'))).toBe(false)
  })

  it('signs in, shows the profile list, and signs out again', async () => {
    const server = new FakeAdminServer()
    server.seedProfile({ name: 'Wedding' })
    renderAdmin('/admin', { server })
    await signIn()
    expect(await screen.findByText('Signed in as admin')).toBeInTheDocument()
    expect(await screen.findByText('Wedding')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Admin sign in' })).toBeInTheDocument()
    expect(screen.queryByText('Wedding')).not.toBeInTheDocument()
    expect(server.signedIn).toBe(false)
  })

  it('reports a wrong password and clears the password field', async () => {
    renderAdmin('/admin')
    await signIn('wrong password here')
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong username or password.')
    expect(screen.getByLabelText('Password')).toHaveValue('')
  })

  it('shows the throttle wait time from Retry-After', async () => {
    const server = new FakeAdminServer()
    server.throttleSeconds = 240
    renderAdmin('/admin', { server })
    await signIn()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Too many attempts. Try again in 240 seconds.',
    )
  })

  it('returns to sign-in with an expiry message when the session ends', async () => {
    const server = new FakeAdminServer()
    server.seedProfile({ name: 'Wedding' })
    renderAdmin('/admin', { server })
    await signIn()
    expect(await screen.findByText('Wedding')).toBeInTheDocument()

    server.signedIn = false // idle/absolute expiry or backend restart
    await userEvent.click(screen.getByRole('checkbox', { name: 'Show deleted profiles' }))
    expect(await screen.findByText('Your session expired. Sign in again.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Admin sign in' })).toBeInTheDocument()
    expect(screen.queryByText('Wedding')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toHaveValue('') // the old password is not kept

    await signIn()
    expect(await screen.findByText('Wedding')).toBeInTheDocument()
  })

  it('resumes an existing session after a reload without asking again', async () => {
    const server = new FakeAdminServer()
    server.signedIn = true
    server.seedProfile({ name: 'Conference' })
    renderAdmin('/admin', { server })
    expect(await screen.findByText('Conference')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Admin sign in' })).toBeNull())
  })

  it('does not pretend to sign out when the logout request fails (P4-003)', async () => {
    const server = new FakeAdminServer()
    server.seedProfile({ name: 'Wedding' })
    renderAdmin('/admin', { server })
    await signIn()
    expect(await screen.findByText('Wedding')).toBeInTheDocument()

    server.logoutNetworkFailure = true
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Sign-out did not finish, so this admin session may still be active.',
    )
    expect(screen.queryByText('Wedding')).not.toBeInTheDocument() // data hidden meanwhile
    expect(screen.queryByRole('heading', { name: 'Admin sign in' })).toBeNull()
    expect(server.signedIn).toBe(true)

    server.logoutNetworkFailure = false
    await userEvent.click(screen.getByRole('button', { name: 'Try sign out again' }))
    expect(await screen.findByRole('heading', { name: 'Admin sign in' })).toBeInTheDocument()
    expect(server.signedIn).toBe(false)
  })

  it('refreshes a stale CSRF token so sign-out really revokes the session (P4-003)', async () => {
    const server = new FakeAdminServer()
    renderAdmin('/admin', { server })
    await signIn()
    expect(await screen.findByText('Signed in as admin')).toBeInTheDocument()

    server.csrf = 'rotated-'.padEnd(43, 'x') // e.g. a newer login in another tab
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Admin sign in' })).toBeInTheDocument()
    expect(server.signedIn).toBe(false)
  })

  it('offers a large Admin link on the home page', async () => {
    renderAdmin('/')
    const link = await screen.findByRole('link', { name: 'Admin' })
    expect(link).toHaveAttribute('href', '/admin')
  })
})
