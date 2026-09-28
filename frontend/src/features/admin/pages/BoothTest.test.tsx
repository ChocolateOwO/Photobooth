import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

/**
 * "Test booth": the organizer runs the real booth screens, with the real camera, against a saved
 * profile. Nothing here may change that profile, and the drawn test camera of the automated
 * tests must never be reachable from this page.
 */

class StubStream {
  stopped = 0
  getTracks() {
    return [{ stop: () => (this.stopped += 1), readyState: 'live' }]
  }
  getVideoTracks() {
    return this.getTracks()
  }
}

let streams: StubStream[] = []

function withCameras(devices: { deviceId: string; label: string }[], allowed = true) {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      enumerateDevices: async () => devices.map((device) => ({ ...device, kind: 'videoinput' })),
      getUserMedia: async () => {
        if (!allowed) {
          const error = new Error('blocked')
          error.name = 'NotAllowedError'
          throw error
        }
        const stream = new StubStream()
        streams.push(stream)
        return stream
      },
    },
  })
}

function signedInServer(options: { builtins?: boolean } = {}) {
  const server = new FakeAdminServer(options)
  server.signedIn = true
  return server
}

/** A signed-in Admin with exactly one frame, so the booth carousel holds a single slide. */
function serverWithOneFrame() {
  const server = signedInServer({ builtins: false })
  server.seedFrame('print_4x6', 'Gold print')
  server.seedProfile({ name: 'Live event', enabled_layouts: ['print_4x6'] }, { is_active: true })
  return server
}

beforeEach(() => {
  streams = []
  ;(globalThis as { MediaStream?: unknown }).MediaStream = StubStream
  localStorage.clear()
  withCameras([{ deviceId: 'built-in', label: 'Built-in camera' }])
})

afterEach(() => {
  vi.restoreAllMocks()
  Reflect.deleteProperty(navigator, 'mediaDevices')
})

describe('Admin "Test booth"', () => {
  it('is reachable from the Admin menu', async () => {
    renderAdmin('/admin', { server: signedInServer() })
    const link = await screen.findByRole('link', { name: 'Test booth' })
    expect(link).toHaveAttribute('href', '/admin/test')
    await userEvent.click(link)
    expect(await screen.findByRole('heading', { name: 'Test booth' })).toBeInTheDocument()
  })

  it('needs an admin session, like the rest of Admin', async () => {
    renderAdmin('/admin/test', { server: new FakeAdminServer() }) // not signed in
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Test booth' })).toBeNull()
  })

  it('lists saved events, starting with the live one, and tries one without activating it', async () => {
    const server = signedInServer()
    server.seedFrame('print_4x6', 'Gold print')
    const live = server.seedProfile({ name: 'Live event' }, { is_active: true })
    const draft = server.seedProfile({ name: 'Next week', enabled_layouts: ['print_4x6'] })
    renderAdmin('/admin/test', { server })

    const events = await screen.findByLabelText('Event to try')
    await waitFor(() => expect(within(events).getAllByRole('option')).toHaveLength(2))
    expect((events as HTMLSelectElement).value).toBe(live.id) // the live one by default
    expect(within(events).getByRole('option', { name: /Live event/ }).textContent).toContain(
      'live now',
    )

    await userEvent.selectOptions(events, draft.id)
    await userEvent.click(screen.getByRole('button', { name: 'Start booth test' }))

    // The booth's own start screen appears, for the profile being tried.
    expect(await screen.findByTestId('booth-shell')).toBeInTheDocument()
    expect(screen.getByTestId('test-banner')).toHaveTextContent('TEST')
    await waitFor(() => expect(server.boothTestMenus).toContain(draft.id))
    // Nothing was activated and nothing was written to the profile.
    const profiles = [...server.profiles.values()]
    expect(profiles.find((profile) => profile.is_active)?.id).toBe(live.id)
    expect(server.profiles.get(draft.id)?.revision).toBe(draft.revision)
    expect(server.profiles.get(draft.id)?.settings).toEqual(draft.settings)
  })

  it('offers the machine cameras and remembers the chosen one', async () => {
    withCameras([
      { deviceId: 'built-in', label: 'Built-in camera' },
      { deviceId: 'usb', label: 'Event camera' },
    ])
    const server = signedInServer()
    server.seedProfile({ name: 'Live event' }, { is_active: true })
    renderAdmin('/admin/test', { server })

    const picker = await screen.findByLabelText('Camera')
    await waitFor(() => expect(within(picker).getAllByRole('option')).toHaveLength(3))
    expect(within(picker).getByRole('option', { name: 'Event camera' })).toBeInTheDocument()
    // The drawn camera of the automated tests is not among them.
    expect(within(picker).queryByRole('option', { name: /Test camera/ })).toBeNull()

    await userEvent.selectOptions(picker, 'usb')
    expect(localStorage.getItem('pb.booth.cameraDevice')).toBe('usb')
  })

  it('uses the real camera: a blocked one is reported, never replaced by drawn pictures', async () => {
    withCameras([{ deviceId: 'built-in', label: 'Built-in camera' }], false)
    const server = serverWithOneFrame()
    renderAdmin('/admin/test', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Start booth test' }))

    // Through the booth's own screens: start, choose the frame, then the camera speaks up.
    await userEvent.click(await screen.findByRole('button', { name: 'Start' }))
    const slide = await screen.findByTestId('frame-slide')
    await userEvent.click(within(slide).getByRole('button', { name: 'Use this frame' }))
    await userEvent.click(screen.getByRole('button', { name: 'Start with this frame' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The camera is blocked for this booth')
    expect(screen.queryByText('Test camera')).toBeNull()
  })

  it('leaving the test stops the camera and clears what the test made', async () => {
    const server = serverWithOneFrame()
    renderAdmin('/admin/test', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Start booth test' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Start' }))
    const slide = await screen.findByTestId('frame-slide')
    await userEvent.click(within(slide).getByRole('button', { name: 'Use this frame' }))
    await userEvent.click(screen.getByRole('button', { name: 'Start with this frame' }))
    await screen.findByLabelText('Camera preview')
    await waitFor(() => expect(streams.length).toBeGreaterThan(0))

    const cleanupsBefore = server.boothTestCleanups
    await userEvent.click(screen.getByRole('button', { name: 'Exit test' }))
    expect(await screen.findByRole('button', { name: 'Start booth test' })).toBeInTheDocument()
    // Every camera track of the test is stopped, and its data is cleared away.
    await waitFor(() => expect(streams.every((stream) => stream.stopped > 0)).toBe(true))
    expect(server.boothTestCleanups).toBeGreaterThan(cleanupsBefore)
  })

  it('sets Admin aside while the test runs, and brings it back on Exit test', async () => {
    const server = serverWithOneFrame()
    renderAdmin('/admin/test', { server })
    // Setting the test up is an ordinary Admin page.
    expect(await screen.findByRole('navigation')).toBeInTheDocument()
    expect(screen.getByText(/Signed in as/)).toBeInTheDocument()
    expect(screen.getByTestId('dummy-badge')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Start booth test' }))
    await screen.findByTestId('booth-shell')
    // Running it is the participant's whole display: no header, no navigation, no badge.
    expect(screen.queryByRole('navigation')).toBeNull()
    expect(screen.queryByText(/Signed in as/)).toBeNull()
    expect(screen.queryByTestId('dummy-badge')).toBeNull()
    expect(document.documentElement).toHaveAttribute('data-booth-immersive')
    // Only the mark and the way out stay on top.
    expect(screen.getByTestId('test-banner')).toHaveTextContent('TEST')

    await userEvent.click(screen.getByRole('button', { name: 'Exit test' }))
    expect(await screen.findByRole('button', { name: 'Start booth test' })).toBeInTheDocument()
    expect(screen.getByRole('navigation')).toBeInTheDocument()
    expect(screen.getByTestId('dummy-badge')).toBeInTheDocument()
    expect(document.documentElement).not.toHaveAttribute('data-booth-immersive')
  })

  it('asks the browser for the whole display, and runs anyway when it refuses', async () => {
    const server = serverWithOneFrame()
    const refuse = vi.fn().mockRejectedValue(new Error('denied'))
    Object.defineProperty(document.documentElement, 'requestFullscreen', {
      configurable: true,
      value: refuse,
    })
    try {
      renderAdmin('/admin/test', { server })
      await userEvent.click(await screen.findByRole('button', { name: 'Start booth test' }))
      // Asked from the press itself, which is the only moment a browser grants it.
      expect(refuse).toHaveBeenCalledTimes(1)
      // Refused: the booth still takes the window and the test runs.
      expect(await screen.findByTestId('booth-shell')).toBeInTheDocument()
      expect(screen.queryByRole('navigation')).toBeNull()
    } finally {
      Reflect.deleteProperty(document.documentElement, 'requestFullscreen')
    }
  })

  it('dresses the test in the event being tried, not in Admin colours', async () => {
    const server = signedInServer({ builtins: false })
    server.seedFrame('print_4x6', 'Gold print')
    server.seedProfile(
      { name: 'Live event', enabled_layouts: ['print_4x6'] },
      { is_active: true },
    )
    const other = server.seedProfile({ name: 'Next week', enabled_layouts: ['print_4x6'] })
    // The two events look nothing alike.
    const draft = server.profiles.get(other.id)
    if (draft) draft.settings.theme.tokens.primary_bg = '#AA3311'
    renderAdmin('/admin/test', { server })

    const events = await screen.findByLabelText('Event to try')
    await waitFor(() => expect(within(events).getAllByRole('option')).toHaveLength(2))
    await userEvent.selectOptions(events, other.id)
    await userEvent.click(screen.getByRole('button', { name: 'Start booth test' }))
    const screenEl = await screen.findByTestId('start-screen')
    const themed = screenEl.closest('[data-event-theme]') as HTMLElement
    // The participant surface wears the tried event's own tokens; nothing is an Admin colour.
    expect(themed.style.getPropertyValue('--ev-primary-bg')).toBe('#AA3311')
    expect(themed.style.getPropertyValue('--ev-background')).toBe(
      draft?.settings.theme.tokens.background,
    )
    // Trying it changed nothing about it.
    expect([...server.profiles.values()].find((p) => p.is_active)?.settings.name).toBe('Live event')
    expect(server.profiles.get(other.id)?.revision).toBe(other.revision)
  })

  it('clears leftovers when the page is opened and when it is left', async () => {
    const server = signedInServer()
    server.seedProfile({ name: 'Live event' }, { is_active: true })
    const view = renderAdmin('/admin/test', { server })
    await screen.findByRole('heading', { name: 'Test booth' })
    await waitFor(() => expect(server.boothTestCleanups).toBe(1)) // whatever an earlier test left
    view.unmount()
    await waitFor(() => expect(server.boothTestCleanups).toBe(2))
  })
})
