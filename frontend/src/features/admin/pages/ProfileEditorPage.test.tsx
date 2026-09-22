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

    // The start screen shows only the logo and the Start button (never the title or subtitle).
    const preview = screen.getByTestId('event-preview')
    expect(within(preview).getByRole('button', { name: 'Go' })).toBeInTheDocument()
    expect(within(preview).getByRole('img', { name: 'Event logo' })).toBeInTheDocument()
    expect(within(preview).queryByText('Congratulations!')).toBeNull()
    expect(within(preview).queryByText('Tap start when ready')).toBeNull()
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
    // The result is a small centred pop-up, not a banner above the form.
    const done = await screen.findByRole('alertdialog', { name: 'Saved' })
    expect(done).toHaveTextContent('Profile saved successfully.')
    expect(screen.queryByRole('status', { name: /Saved/ })).toBeNull()
  })

  it('updates the live preview on every keystroke', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    const start = await screen.findByLabelText('Start button text')
    await userEvent.clear(start)
    await userEvent.type(start, 'Hi')
    expect(within(screen.getByTestId('event-preview')).getByRole('button', { name: 'Hi' })).toBeInTheDocument()
    // An empty text falls back to Start.
    await userEvent.clear(start)
    expect(within(screen.getByTestId('event-preview')).getByRole('button', { name: 'Start' })).toBeInTheDocument()
  })

  it('lists every missing field in one pop-up and goes to the first problem', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await userEvent.clear(await screen.findByLabelText('Inactivity timeout (seconds)'))
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Some information is missing or invalid' })
    const items = within(dialog).getAllByRole('listitem').map((li) => li.textContent)
    expect(items).toEqual([
      'Profile name is required.',
      'Title is required.',
      'Inactivity timeout must be between 30 and 900 seconds.',
    ])
    expect(server.requests.some((r) => r.method === 'POST' && r.path === '/api/admin/profiles')).toBe(false)
    // Every problem field is highlighted inline as well.
    for (const label of ['Profile name', 'Title', 'Inactivity timeout (seconds)']) {
      expect(screen.getByLabelText(label)).toHaveAttribute('aria-invalid', 'true')
    }
    expect(screen.getByLabelText('Profile name')).toHaveAccessibleDescription(
      'Only admins see this name. It helps you find the profile later. Profile name is required.',
    )

    await userEvent.click(within(dialog).getByRole('button', { name: 'Go to first problem' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    await waitFor(() => expect(screen.getByLabelText('Profile name')).toHaveFocus())

    // Fixing a field removes its highlight at once.
    await userEvent.type(screen.getByLabelText('Profile name'), 'Fixed')
    expect(screen.getByLabelText('Profile name')).not.toHaveAttribute('aria-invalid')
    expect(screen.getByLabelText('Title')).toHaveAttribute('aria-invalid', 'true')

    // Closing the pop-up (Escape) also lands on the first remaining problem.
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await screen.findByRole('alertdialog', { name: 'Some information is missing or invalid' })
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.getByLabelText('Title')).toHaveFocus())
  })

  it('refuses unsupported or oversized images before uploading', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    const input = await screen.findByLabelText('Background image')
    await userEvent.upload(input, new File(['<svg/>'], 'x.svg', { type: 'image/svg+xml' }), {
      applyAccept: false,
    })
    const refused = await screen.findByRole('alertdialog', { name: 'The background was not uploaded' })
    expect(refused).toHaveTextContent('Background must be a PNG or JPEG image.')
    await userEvent.click(within(refused).getByRole('button', { name: 'Close' }))
    await userEvent.upload(input, png('big.png', 12 * 1024 * 1024 + 1))
    expect(
      await screen.findByRole('alertdialog', { name: 'The background was not uploaded' }),
    ).toHaveTextContent('Background must be 12 MB or smaller.')
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
    const save = screen.getByRole('button', { name: 'Save profile' })
    await userEvent.click(save)
    const saved = await screen.findByRole('alertdialog', { name: 'Saved' })
    expect(saved).toHaveTextContent('Profile saved successfully.')
    expect(server.profiles.get(wedding.id)?.revision).toBe(2)
    await userEvent.click(within(saved).getByRole('button', { name: 'Close' }))
    expect(save).toHaveFocus() // focus goes back to the control that saved

    server.bumpRevision(wedding.id, { title: 'Changed in another tab' })
    await userEvent.type(screen.getByLabelText('Title'), '!')
    await userEvent.click(save)
    const conflict = await screen.findByRole('alertdialog', { name: 'Changed somewhere else' })
    expect(conflict).toHaveTextContent('This profile was changed somewhere else. Reload to get the latest version.')
    expect(server.profiles.get(wedding.id)?.settings.title).toBe('Changed in another tab')

    await userEvent.click(within(conflict).getByRole('button', { name: 'Reload latest' }))
    await waitFor(() => expect(screen.getByLabelText('Title')).toHaveValue('Changed in another tab'))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    await userEvent.click(save)
    expect(await screen.findByRole('alertdialog', { name: 'Saved' })).toBeInTheDocument()
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
    expect(await screen.findByRole('alertdialog', { name: 'Saved' })).toBeInTheDocument()
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
    const failed = await screen.findByRole('alertdialog', { name: 'The profile was not saved' })
    expect(failed).toHaveTextContent('another live profile already uses this name')
  })

  it('has exactly one configurable preview whose size and orientation can be changed', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    await screen.findByLabelText('Profile name')
    expect(screen.queryByText('Phone width')).toBeNull()
    expect(screen.queryByTestId('event-preview-phone')).toBeNull()
    expect(screen.getAllByTestId('preview-viewport')).toHaveLength(1)
    const viewport = screen.getByTestId('preview-viewport')
    expect(screen.getByTestId('preview-size')).toHaveTextContent('1080 × 1920 px')
    expect(viewport).toHaveStyle({ width: '1080px', height: '1920px' })
    const orientation = screen.getByRole('group', { name: 'Orientation' })
    expect(within(orientation).getByRole('button', { name: 'Portrait' })).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(within(orientation).getByRole('button', { name: 'Landscape' }))
    expect(screen.getByTestId('preview-size')).toHaveTextContent('1920 × 1080 px')
    expect(viewport).toHaveStyle({ width: '1920px', height: '1080px' })

    await userEvent.click(screen.getByRole('button', { name: 'Swap width and height' }))
    expect(screen.getByTestId('preview-size')).toHaveTextContent('1080 × 1920 px')

    const width = screen.getByLabelText('Preview width in pixels')
    await userEvent.clear(width)
    await userEvent.type(width, '800')
    const height = screen.getByLabelText('Preview height in pixels')
    await userEvent.clear(height)
    await userEvent.type(height, '600')
    expect(screen.getByTestId('preview-size')).toHaveTextContent('800 × 600 px')
    expect(within(orientation).getByRole('button', { name: 'Landscape' })).toHaveAttribute('aria-pressed', 'true')

    // Out-of-range values are explained and never reach the preview.
    await userEvent.clear(width)
    await userEvent.type(width, '10')
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a whole number from 320 to 3840 px.')
    expect(width).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByTestId('preview-size')).toHaveTextContent('800 × 600 px')
    await userEvent.clear(width)
    await userEvent.click(width)
    await userEvent.paste('99999')
    expect(screen.getByRole('alert')).toHaveTextContent('The preview keeps 800 × 600 px.')
    expect(screen.getByTestId('preview-size')).toHaveTextContent('800 × 600 px')

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Common screen sizes' }), 'Phone')
    expect(screen.getByTestId('preview-size')).toHaveTextContent('390 × 844 px')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows only the background, one logo and the Start button on the start screen', async () => {
    const server = signedInServer()
    const wedding = server.seedProfile({ name: 'Wedding', title: 'Big day', subtitle: 'Smile' })
    renderAdmin(`/admin/profiles/${wedding.id}`, { server })
    const start = await screen.findByTestId('start-screen')
    // No logo configured: the neutral Photobooth mark, never a broken image.
    expect(within(start).getByRole('img', { name: 'Photobooth' })).toBeInTheDocument()
    expect(within(start).getAllByRole('button')).toHaveLength(1)
    expect(within(start).getByRole('button')).toHaveTextContent(wedding.settings.start_button_text || 'Start')
    const preview = screen.getByTestId('event-preview')
    for (const gone of ['Big day', 'Smile', 'Back', 'Print', 'Email for your photos', 'Your photos are ready.']) {
      expect(within(preview).queryByText(gone)).toBeNull()
    }
    expect(within(preview).queryByRole('textbox')).toBeNull()
    expect(within(preview).queryByText(/frames? to choose from/)).toBeNull()
  })
})
