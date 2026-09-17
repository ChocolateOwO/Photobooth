import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

function signedInServer() {
  const server = new FakeAdminServer()
  server.signedIn = true
  return server
}

function png(name = 'logo.png', bytes = 128): File {
  return new File([new Uint8Array(bytes)], name, { type: 'image/png' })
}

describe('ProfileEditorPage', () => {
  it('creates a profile with every preparation-screen setting and reopens it', async () => {
    const server = signedInServer()
    const { router } = renderAdmin('/admin/profiles/new', { server })

    expect(await screen.findByRole('heading', { name: 'New Event Profile' })).toBeInTheDocument()
    await userEvent.type(await screen.findByLabelText('Profile name'), 'Graduation')
    await userEvent.type(screen.getByLabelText('Title'), 'Congratulations!')
    await userEvent.type(screen.getByLabelText('Subtitle'), 'Tap start when ready')
    await userEvent.clear(screen.getByLabelText('Start button text'))
    await userEvent.type(screen.getByLabelText('Start button text'), 'Go')
    fireEvent.input(screen.getByLabelText('Primary color'), { target: { value: '#aa0011' } })
    await userEvent.click(screen.getByRole('checkbox', { name: '4x6 print' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Mirror the camera preview' }))
    await userEvent.clear(screen.getByLabelText('Inactivity timeout (seconds)'))
    await userEvent.type(screen.getByLabelText('Inactivity timeout (seconds)'), '300')
    await userEvent.click(screen.getByRole('radio', { name: 'Retake all photos' }))
    await userEvent.upload(screen.getByLabelText('Logo image'), png())
    expect(await screen.findByRole('img', { name: 'Logo preview' })).toBeInTheDocument()
    expect(await screen.findByText('640 × 480 px')).toBeInTheDocument()
    expect(screen.getByText('Countdown: 5 seconds before each photo')).toBeInTheDocument()

    const preview = screen.getByTestId('preparation-preview')
    expect(within(preview).getByText('Congratulations!')).toBeInTheDocument()
    expect(within(preview).getByText('Go')).toBeInTheDocument()
    expect(within(preview).getByRole('img', { name: 'Preview logo' })).toBeInTheDocument()
    expect(within(preview).getByText('Mirror: off')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/admin\/profiles\/0{8}-/))

    const saved = [...server.profiles.values()][0]
    expect(saved?.settings).toMatchObject({
      name: 'Graduation',
      title: 'Congratulations!',
      subtitle: 'Tap start when ready',
      start_button_text: 'Go',
      primary_color: '#AA0011',
      enabled_layouts: ['strip_2x6', 'print_4x6'],
      mirror: false,
      inactivity_timeout_s: 300,
      retake_mode: 'all',
      delivery_mode: 'local_link',
      countdown_seconds: 5,
    })
    expect(saved?.settings.logo_asset_id).toBe([...server.assets.keys()][0])
    expect(await screen.findByRole('heading', { name: 'Edit Event Profile' })).toBeInTheDocument()
    expect(screen.getByLabelText('Profile name')).toHaveValue('Graduation')
  })

  it('updates the live preview on every keystroke', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    const title = await screen.findByLabelText('Title')
    await userEvent.type(title, 'Hi')
    expect(within(screen.getByTestId('preparation-preview')).getByText('Hi')).toBeInTheDocument()
  })

  it('blocks saving without required fields or layouts', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await userEvent.click(await screen.findByRole('checkbox', { name: '2x6 photo strip' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    const alerts = await screen.findAllByRole('alert')
    const text = alerts.map((a) => a.textContent).join(' ')
    expect(text).toContain('Profile name is required.')
    expect(text).toContain('Choose at least one layout.')
    expect(server.requests.some((r) => r.method === 'POST' && r.path === '/api/admin/profiles')).toBe(false)
  })

  it('refuses unsupported or oversized images before uploading', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    const input = await screen.findByLabelText('Background image')
    await userEvent.upload(input, new File(['<svg/>'], 'x.svg', { type: 'image/svg+xml' }), {
      applyAccept: false,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Background must be a PNG or JPEG image.')
    await userEvent.upload(input, png('big.png', 12 * 1024 * 1024 + 1))
    expect(await screen.findByRole('alert')).toHaveTextContent('Background must be 12 MB or smaller.')
    expect(server.assets.size).toBe(0)
  })

  it('edits a saved profile with its revision and reports a stale edit', async () => {
    const server = signedInServer()
    const wedding = server.seedProfile({ name: 'Wedding', title: 'Old title' })
    renderAdmin(`/admin/profiles/${wedding.id}`, { server })

    const title = await screen.findByLabelText('Title')
    expect(title).toHaveValue('Old title')
    await userEvent.clear(title)
    await userEvent.type(title, 'New title')
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Saved')
    expect(server.profiles.get(wedding.id)?.revision).toBe(2)

    server.bumpRevision(wedding.id, { title: 'Changed in another tab' })
    await userEvent.type(screen.getByLabelText('Title'), '!')
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This profile was changed somewhere else. Reload to get the latest version.',
    )
    expect(server.profiles.get(wedding.id)?.settings.title).toBe('Changed in another tab')

    await userEvent.click(screen.getByRole('button', { name: 'Reload latest' }))
    await waitFor(() => expect(screen.getByLabelText('Title')).toHaveValue('Changed in another tab'))
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Saved')
    expect(server.profiles.get(wedding.id)?.revision).toBe(4)
  })

  it('shows deleted profiles read-only', async () => {
    const server = signedInServer()
    const old = server.seedProfile({ name: 'Old' }, { deleted_at: '2026-09-17T11:00:00Z' })
    renderAdmin(`/admin/profiles/${old.id}`, { server })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This profile is deleted. Restore it from the list to edit.',
    )
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled()
  })

  it('shows server validation messages', async () => {
    const server = signedInServer()
    server.seedProfile({ name: 'Taken' })
    renderAdmin('/admin/profiles/new', { server })
    await userEvent.type(await screen.findByLabelText('Profile name'), 'taken')
    await userEvent.type(screen.getByLabelText('Title'), 'Hello')
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('another live profile already uses this name')
  })
})
