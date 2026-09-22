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
    await userEvent.click(screen.getByRole('radio', { name: /^Blush Wedding/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Mirror the camera preview' }))
    await userEvent.clear(screen.getByLabelText('Inactivity timeout (seconds)'))
    await userEvent.type(screen.getByLabelText('Inactivity timeout (seconds)'), '300')
    await userEvent.click(screen.getByRole('radio', { name: 'Retake all photos' }))
    await userEvent.upload(screen.getByLabelText('Logo image'), png())
    expect(await screen.findByRole('img', { name: 'Logo preview' })).toBeInTheDocument()
    expect(await screen.findByText('640 × 480 px')).toBeInTheDocument()
    expect(screen.getByText('Countdown: 5 seconds before each photo')).toBeInTheDocument()

    const preview = screen.getByTestId('event-preview')
    expect(within(preview).getByText('Congratulations!')).toBeInTheDocument()
    expect(within(preview).getByText('Go')).toBeInTheDocument()
    expect(within(preview).getByRole('img', { name: 'Preview logo' })).toBeInTheDocument()
    expect(
      within(screen.getByTestId('preparation-preview')).getByText('Mirror: off'),
    ).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/admin\/profiles\/0{8}-/))

    const saved = [...server.profiles.values()][0]
    expect(saved?.settings).toMatchObject({
      name: 'Graduation',
      title: 'Congratulations!',
      subtitle: 'Tap start when ready',
      start_button_text: 'Go',
      theme: { source: 'preset', preset: 'blush_wedding' },
      // A new profile offers every built-in frame; participants choose at the booth.
      available_frames: server.builtinIds(),
      allow_surprise_me: false,
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
    expect(within(screen.getByTestId('event-preview')).getByText('Hi')).toBeInTheDocument()
    expect(within(screen.getByTestId('event-preview-phone')).getByText('Hi')).toBeInTheDocument()
  })

  it('blocks saving without required fields', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Save profile' }))
    const alerts = await screen.findAllByRole('alert')
    const text = alerts.map((a) => a.textContent).join(' ')
    expect(text).toContain('Profile name is required.')
    expect(text).toContain('Title is required.')
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

  it('keeps edits made while an upload is in flight and both image selections (P4-001)', async () => {
    const server = signedInServer()
    let releaseUpload = () => {}
    server.uploadGate = new Promise<void>((resolve) => {
      releaseUpload = resolve
    })
    renderAdmin('/admin/profiles/new', { server })

    await userEvent.upload(await screen.findByLabelText('Logo image'), png('logo.png'))
    await userEvent.upload(screen.getByLabelText('Background image'), png('bg.png'))
    await userEvent.type(screen.getByLabelText('Title'), 'Typed during upload')
    await userEvent.type(screen.getByLabelText('Profile name'), 'Slow uploads')
    releaseUpload()

    expect(await screen.findByRole('img', { name: 'Logo preview' })).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: 'Background preview' })).toBeInTheDocument()
    expect(screen.getByLabelText('Title')).toHaveValue('Typed during upload')
    expect(screen.getByLabelText('Profile name')).toHaveValue('Slow uploads')
  })

  it('does not save while an image upload is still pending (P4-002)', async () => {
    const server = signedInServer()
    const wedding = server.seedProfile({ name: 'Wedding' })
    let releaseUpload = () => {}
    server.uploadGate = new Promise<void>((resolve) => {
      releaseUpload = resolve
    })
    renderAdmin(`/admin/profiles/${wedding.id}`, { server })

    await userEvent.upload(await screen.findByLabelText('Logo image'), png())
    const save = screen.getByRole('button', { name: 'Save profile' })
    await waitFor(() => expect(save).toBeDisabled())
    expect(screen.getByText('Wait for image uploads to finish before saving.')).toBeInTheDocument()
    fireEvent.submit(save.closest('form') as HTMLFormElement)
    expect(server.requests.some((r) => r.method === 'PUT')).toBe(false)

    releaseUpload()
    await waitFor(() => expect(save).toBeEnabled())
    await userEvent.click(save)
    expect(await screen.findByRole('status')).toHaveTextContent('Saved')
    const logoId = [...server.assets.keys()][0]
    expect(server.profiles.get(wedding.id)?.settings.logo_asset_id).toBe(logoId)
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
