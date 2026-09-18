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
    await userEvent.click(screen.getByRole('checkbox', { name: '4x6 print' }))
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
      enabled_layouts: ['strip_2x6', 'print_4x6'],
      // New layouts get the built-in frame of the family already in use (the default: Midnight).
      frame_selections: {
        strip_2x6: server.builtin('midnight', 'strip_2x6').id,
        print_4x6: server.builtin('midnight', 'print_4x6').id,
      },
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

describe('frame selection per layout', () => {
  it('starts with built-in frames, can switch to uploaded ones and warns without a frame', async () => {
    const server = signedInServer()
    const strip = server.seedFrame('strip_2x6', 'Strip gold')
    const print = server.seedFrame('print_4x6', 'Print silver')
    renderAdmin('/admin/profiles/new', { server })

    await userEvent.type(await screen.findByLabelText('Profile name'), 'Expo')
    await userEvent.type(screen.getByLabelText('Title'), 'Welcome')
    // A new profile enables the first layout with the default built-in frame.
    const stripSelect = screen.getByLabelText('Frame for 2x6 photo strip')
    expect(stripSelect).toHaveValue(server.builtin('midnight', 'strip_2x6').id)
    expect(within(stripSelect).getByRole('option', { name: 'Midnight (Built-in)' })).toBeInTheDocument()
    expect(within(stripSelect).getByRole('group', { name: 'Built-in' })).toBeInTheDocument()
    expect(within(stripSelect).getByRole('group', { name: 'Your frames' })).toBeInTheDocument()
    expect(screen.queryAllByTestId('missing-frame-warning')).toHaveLength(0)
    await userEvent.click(screen.getByRole('checkbox', { name: '4x6 print' }))
    expect(screen.getByLabelText('Frame for 4x6 print')).toHaveValue(
      server.builtin('midnight', 'print_4x6').id,
    )

    // Switching away from a frame is allowed; the missing frame is then clearly marked.
    await userEvent.selectOptions(screen.getByLabelText('Frame for 4x6 print'), '')
    expect(await screen.findByTestId('missing-frame-warning')).toHaveTextContent(
      'No frame selected for 4x6 print. Photos will print without a frame.',
    )
    await userEvent.selectOptions(screen.getByLabelText('Frame for 2x6 photo strip'), strip.id)
    await userEvent.selectOptions(screen.getByLabelText('Frame for 4x6 print'), print.id)
    expect(screen.queryAllByTestId('missing-frame-warning')).toHaveLength(0)
    expect(screen.getByRole('img', { name: '2x6 photo strip frame preview' })).toHaveAttribute(
      'src',
      `/api/admin/frames/${strip.id}/preview/1.jpg?v=${strip.sha256}`,
    )
    // ...and back to a built-in one.
    await userEvent.selectOptions(
      screen.getByLabelText('Frame for 2x6 photo strip'),
      server.builtin('celebration_gold', 'strip_2x6').id,
    )
    expect(
      screen.getByText('Built-in frame. Upload your own under Frames to use a different design.'),
    ).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    expect([...server.profiles.values()][0]?.settings.frame_selections).toEqual({
      strip_2x6: server.builtin('celebration_gold', 'strip_2x6').id,
      print_4x6: print.id,
    })
  })

  it('drops the frame when its layout is switched off', async () => {
    const server = signedInServer()
    const strip = server.seedFrame('strip_2x6', 'Strip gold')
    server.seedFrame('print_4x6', 'Print silver')
    const profile = server.seedProfile({
      name: 'Expo',
      enabled_layouts: ['strip_2x6', 'print_4x6'],
      frame_selections: { strip_2x6: strip.id },
    })
    renderAdmin(`/admin/profiles/${profile.id}`, { server })

    await waitFor(() =>
      expect(screen.getByLabelText('Frame for 2x6 photo strip')).toHaveValue(strip.id),
    )
    await userEvent.click(screen.getByRole('checkbox', { name: '2x6 photo strip' }))
    expect(screen.queryByLabelText('Frame for 2x6 photo strip')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'))
    expect(server.profiles.get(profile.id)?.settings.frame_selections).toEqual({})
    expect(server.profiles.get(profile.id)?.settings.enabled_layouts).toEqual(['print_4x6'])
  })

  it('keeps a saved frame selected and locked while the frame list is loading (P5-005)', async () => {
    const server = signedInServer()
    const strip = server.seedFrame('strip_2x6', 'Strip gold')
    const profile = server.seedProfile({
      name: 'Expo',
      enabled_layouts: ['strip_2x6'],
      frame_selections: { strip_2x6: strip.id },
    })
    let release = () => {}
    server.frameListGate = new Promise<void>((resolve) => {
      release = resolve
    })
    renderAdmin(`/admin/profiles/${profile.id}`, { server })

    const select = await screen.findByLabelText('Frame for 2x6 photo strip')
    expect(select).toHaveValue(strip.id)
    expect(select).toBeDisabled()
    expect(screen.getByText('Loading frames…')).toBeInTheDocument()
    // Not loaded yet is not the same as "no frame selected" or "no frames uploaded".
    expect(screen.queryByTestId('missing-frame-warning')).toBeNull()
    expect(screen.queryByText('Upload a frame for this layout first.')).toBeNull()

    release()
    await waitFor(() => expect(screen.getByLabelText('Frame for 2x6 photo strip')).toBeEnabled())
    expect(screen.getByLabelText('Frame for 2x6 photo strip')).toHaveValue(strip.id)
    expect(screen.getByRole('option', { name: 'Strip gold' })).toBeInTheDocument()
  })

  it('offers a retry when the frame list fails and saving keeps the stored frame (P5-005)', async () => {
    const server = signedInServer()
    const strip = server.seedFrame('strip_2x6', 'Strip gold')
    const profile = server.seedProfile({
      name: 'Expo',
      enabled_layouts: ['strip_2x6'],
      frame_selections: { strip_2x6: strip.id },
    })
    server.frameListFailures = 1
    renderAdmin(`/admin/profiles/${profile.id}`, { server })

    const alert = await screen.findByText(/The frames could not be loaded/)
    expect(screen.getByLabelText('Frame for 2x6 photo strip')).toHaveValue(strip.id)
    expect(screen.getByLabelText('Frame for 2x6 photo strip')).toBeDisabled()
    expect(screen.queryByTestId('missing-frame-warning')).toBeNull()

    await userEvent.type(screen.getByLabelText('Title'), '!')
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.get(profile.id)?.revision).toBe(2))
    expect(server.profiles.get(profile.id)?.settings.frame_selections).toEqual({
      strip_2x6: strip.id,
    })

    await userEvent.click(
      within(alert.closest('[role="alert"]') as HTMLElement).getByRole('button', {
        name: 'Try again',
      }),
    )
    await waitFor(() => expect(screen.getByLabelText('Frame for 2x6 photo strip')).toBeEnabled())
    expect(screen.queryByText(/The frames could not be loaded/)).toBeNull()
  })

  it('points to the frame manager when a layout has no frames at all', async () => {
    const server = new FakeAdminServer({ builtins: false })
    server.signedIn = true
    renderAdmin('/admin/profiles/new', { server })
    expect(await screen.findByText('Upload a frame for this layout first.')).toBeInTheDocument()
    const links = screen.getAllByRole('link', { name: 'Frames' })
    expect(links[0]).toHaveAttribute('href', '/admin/frames')
  })

  it('reports the server reason when a frame does not fit the layout', async () => {
    const server = signedInServer()
    const strip = server.seedFrame('strip_2x6', 'Strip gold')
    const profile = server.seedProfile({
      name: 'Expo',
      enabled_layouts: ['strip_2x6'],
      frame_selections: { strip_2x6: strip.id },
    })
    // Another admin moved this frame to a different layout meanwhile.
    server.frames.set(strip.id, { ...strip, template_key: 'print_3x4' })
    renderAdmin(`/admin/profiles/${profile.id}`, { server })
    await waitFor(() => expect(screen.getByLabelText('Profile name')).toHaveValue('Expo'))
    await userEvent.type(screen.getByLabelText('Title'), '!')
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'that frame does not belong to strip_2x6',
    )
    expect(server.profiles.get(profile.id)?.revision).toBe(1)
  })
})