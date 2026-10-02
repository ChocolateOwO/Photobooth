import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'

import { ApiClientProvider } from '../../shared/api/ApiClientContext'
import { createApiClient, type BoothSessionState, type FrameMenu } from '../../shared/api/client'
import { CameraError, type CameraSource, type CameraView } from '../../shared/camera/camera'
import { CapturePage } from './CapturePage'

/**
 * The camera itself is a port, so these tests drive a stand-in that hands out numbered photos.
 * What is proven here is the booth's behaviour: one countdown per photo, one photo per shot,
 * the event's countdown, the mirror only on the preview, retakes, and every camera problem
 * ending on a screen the participant can get out of.
 */

const SESSION_ID = '22222222-2222-4222-8222-222222222222'

function shots(total: number, done: number, attempt = 1) {
  return Array.from({ length: total }, (_, index) => ({
    shot_index: index + 1,
    attempt_no: index < done ? 1 : attempt,
    done: index < done,
    // Each taken shot carries its own photo, as the server reports it.
    capture_id: index < done ? `capture-${index + 1}` : null,
    version: index < done ? `v${index + 1}` : null,
  }))
}

function visit(overrides: Partial<BoothSessionState> = {}): BoothSessionState {
  const expected = overrides.expected_captures ?? 2
  const taken = overrides.taken ?? 0
  const base: BoothSessionState = {
    id: SESSION_ID,
    is_test: false, // a guest's visit; the organizer's test sets this
    state: 'capturing',
    state_version: 1 + taken,
    countdown_seconds: 3,
    mirror: true,
    retake_mode: 'per_photo',
    expected_captures: expected,
    taken,
    template_key: 'print_3x4',
    layout_label: '3×4',
    frame_id: 'f34',
    shots: shots(expected, taken),
    inactivity_timeout_s: 120,
  }
  return { ...base, ...overrides }
}

/** The three photo sizes and the shape each of them keeps of one photo. */
const LAYOUTS = [
  { id: 'f34', key: 'print_3x4', label: '3×4', captures: 2, slot: { width: 810, height: 540 } },
  { id: 'f46', key: 'print_4x6', label: '4×6', captures: 4, slot: { width: 555, height: 740 } },
  { id: 'fs', key: 'strip_2x6', label: '2×6', captures: 6, slot: { width: 540, height: 405 } },
] as const

const MENU: FrameMenu = {
  frames: LAYOUTS.map((layout) => ({
    id: layout.id,
    name: layout.id === 'f34' ? 'Gold frame' : `Frame ${layout.label}`,
    preview_url: `/api/booth/frames/${layout.id}/preview.jpg?v=1`,
    plan: {
      frame_id: layout.id,
      template_key: layout.key,
      layout_label: layout.label,
      captures: layout.captures,
      outputs: 1,
      photos_per_output: layout.captures,
      output_capture_groups: [[1, 2]],
      output_label: null,
      photo_slot: { ...layout.slot },
    },
  })),
  layouts: [],
  allow_surprise_me: false,
  theme: { background: '#101418', heading: '#FFFFFF', primary_bg: '#2255CC', primary_text: '#FFFFFF' },
  start_screen: { start_button_text: 'Start', logo_url: null, background_url: null },
  countdown_seconds: 3,
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

class FakeCamera implements CameraSource {
  readonly kind = 'test'
  opened = 0
  photos = 0
  stopped = 0
  failWith: CameraError | null = null
  alive = true
  cameras = [{ id: 'fake', label: 'Fake camera' }]
  openedWith: (string | undefined)[] = []

  async devices() {
    return this.cameras
  }

  async open(deviceId?: string): Promise<CameraView> {
    this.opened += 1
    this.openedWith.push(deviceId)
    if (this.failWith) throw this.failWith
    // Arrow functions keep this fake camera's own counters without aliasing `this`.
    const photo = async (): Promise<Blob> => {
      if (!this.alive) throw new CameraError('lost', 'the camera went away')
      this.photos += 1
      return new Blob([`photo-${this.photos}`], { type: 'image/jpeg' })
    }
    return {
      stream: new MediaStream(),
      live: () => this.alive,
      photo,
      stop: () => {
        this.stopped += 1
      },
    }
  }
}

let camera: FakeCamera

interface Sent {
  path: string
  fields: Record<string, string>
  bytes: string
}

function renderCapture(
  handler: (path: string, init?: RequestInit) => Promise<Response>,
): { sent: Sent[] } {
  const sent: Sent[] = []
  const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.body instanceof FormData) {
      const form = init.body
      const file = form.get('file')
      sent.push({
        path,
        fields: Object.fromEntries(
          [...form.entries()].filter(([, value]) => typeof value === 'string'),
        ) as Record<string, string>,
        bytes: file instanceof Blob ? await file.text() : '',
      })
    }
    return handler(path, init)
  })
  const keys = { get: () => 'k'.repeat(43), set: () => undefined, clear: () => undefined }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ApiClientProvider client={createApiClient(fetcher, keys)}>
        <MemoryRouter initialEntries={['/booth/capture']}>
          <Routes>
            <Route path="/booth/capture" element={<CapturePage camera={camera} />} />
            <Route path="/booth/frames" element={<p>the frame screen</p>} />
            <Route path="/booth/decorate" element={<p>the decorate screen</p>} />
            <Route path="/booth/done" element={<p>the take-home screen</p>} />
            <Route path="/booth" element={<p>the start screen</p>} />
          </Routes>
        </MemoryRouter>
      </ApiClientProvider>
    </QueryClientProvider>,
  )
  return { sent }
}

/** A booth that answers like the server: each photo counts once, the set fills up in order. */
function server(session: BoothSessionState = visit()) {
  let current = session
  const handler = async (path: string, init?: RequestInit) => {
    if (path === '/api/booth/frames') return json(MENU)
    if (path.endsWith('/sessions/current')) return json(current)
    if (path.endsWith(`/sessions/${current.id}`)) return json(current) // a plain read
    if (path.endsWith('/captures')) {
      const form = init?.body as FormData
      const shot = Number(form.get('shot_index'))
      const taken = Math.max(current.taken, shot)
      current = {
        ...current,
        taken,
        state_version: current.state_version + 1,
        shots: current.shots.map((entry) =>
          entry.shot_index === shot ? { ...entry, done: true } : entry,
        ),
      }
      const attempt = Number(form.get('attempt_no'))
      current = {
        ...current,
        shots: current.shots.map((entry) =>
          entry.shot_index === shot
            ? { ...entry, capture_id: `capture-${shot}-${attempt}`, version: `v${attempt}` }
            : entry,
        ),
      }
      return json({
        capture_id: `capture-${shot}-${attempt}`,
        shot_index: shot,
        attempt_no: attempt,
        status: 'ok',
        session: current,
      })
    }
    if (path.endsWith('/retake')) {
      const body = JSON.parse(String(init?.body)) as { shot_index?: number }
      current = {
        ...current,
        taken: current.taken - (body.shot_index ? 1 : current.taken),
        state_version: current.state_version + 1,
        shots: current.shots.map((entry) =>
          body.shot_index === undefined || entry.shot_index === body.shot_index
            ? {
                ...entry,
                done: false,
                attempt_no: entry.attempt_no + 1,
                capture_id: null,
                version: null,
              }
            : entry,
        ),
      }
      return json(current)
    }
    if (path.endsWith('/finish')) {
      current = { ...current, state: 'reviewing' }
      return json(current)
    }
    if (path.endsWith('/give-up')) {
      current = { ...current, state: 'cancelled' }
      return json(current)
    }
    return json({ detail: 'nope' }, 404)
  }
  return { handler, state: () => current }
}

/** The small pictures beside the camera, one place per shot (not the big review picture). */
function thumbnails(): HTMLElement[] {
  return within(screen.getByTestId('captured-photos')).queryAllByRole('img')
}

/** Let the booth run through one countdown and the photo that follows it. */
async function oneShot(seconds = 3) {
  await act(async () => {
    vi.advanceTimersByTime(400) // the small pause before a countdown starts
  })
  await act(async () => {
    vi.advanceTimersByTime(seconds * 1000)
  })
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
  await act(async () => {
    vi.advanceTimersByTime(1000) // the pause between photos
  })
}

/** jsdom has no camera plumbing; the booth only needs a stream object to hand to the preview. */
class StubStream {
  getTracks() {
    return []
  }
  getVideoTracks() {
    return []
  }
}

beforeEach(() => {
  ;(globalThis as { MediaStream?: unknown }).MediaStream = StubStream
  camera = new FakeCamera()
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('CapturePage (booth)', () => {
  it('takes one photo per shot, counting down each time, and shows the progress', async () => {
    const booth = server(visit({ expected_captures: 2 }))
    const { sent } = renderCapture(booth.handler)
    expect(await screen.findByTestId('capture-progress')).toHaveTextContent('Photo 1 of 2')

    await oneShot()
    expect(screen.getByTestId('capture-progress')).toHaveTextContent('Photo 2 of 2')
    await oneShot()
    expect(await screen.findByText('All photos taken')).toBeInTheDocument()

    expect(sent.map((call) => call.fields.shot_index)).toEqual(['1', '2'])
    expect(sent.map((call) => call.fields.attempt_no)).toEqual(['1', '1'])
    expect(new Set(sent.map((call) => call.bytes)).size).toBe(2) // two different photos
    expect(new Set(sent.map((call) => call.fields.idempotency_key)).size).toBe(2)
  })

  it('takes all six photos of a 2×6 strip, each one its own picture', async () => {
    const booth = server(visit({ expected_captures: 6, template_key: 'strip_2x6' }))
    const { sent } = renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    for (let shot = 1; shot <= 6; shot++) await oneShot()

    expect(await screen.findByText('All photos taken')).toBeInTheDocument()
    expect(sent.map((call) => call.fields.shot_index)).toEqual(['1', '2', '3', '4', '5', '6'])
    expect(new Set(sent.map((call) => call.bytes)).size).toBe(6)
    expect(camera.photos).toBe(6)
  })

  it('counts down from the event own countdown, once per photo', async () => {
    const booth = server(visit({ expected_captures: 2, countdown_seconds: 7 }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await act(async () => {
      vi.advanceTimersByTime(400)
    })
    expect(screen.getByTestId('countdown')).toHaveTextContent('7')
    await act(async () => {
      vi.advanceTimersByTime(3000)
    })
    expect(screen.getByTestId('countdown')).toHaveTextContent('4')
    await act(async () => {
      vi.advanceTimersByTime(4000)
      await Promise.resolve()
    })
    await waitFor(() => expect(screen.getByTestId('capture-progress')).toHaveTextContent('Photo 2 of 2'))
  })

  it('mirrors the live picture only, and never the photo that is kept', async () => {
    const booth = server(visit({ expected_captures: 1, mirror: true }))
    const { sent } = renderCapture(booth.handler)
    const preview = await screen.findByLabelText('Camera preview')
    expect(preview).toHaveAttribute('data-mirrored')
    await oneShot()
    // The photo is whatever the camera produced: the booth does not flip it before sending.
    expect(sent).toHaveLength(1)
    expect(sent[0]?.bytes).toBe('photo-1')
  })

  it('leaves the preview unmirrored when the event says so', async () => {
    const booth = server(visit({ expected_captures: 1, mirror: false }))
    renderCapture(booth.handler)
    expect(await screen.findByLabelText('Camera preview')).not.toHaveAttribute('data-mirrored')
  })

  it('takes one photo again without changing the frame or the number of photos', async () => {
    const booth = server(visit({ expected_captures: 2, retake_mode: 'per_photo' }))
    const { sent } = renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    await oneShot()
    await screen.findByText('All photos taken')

    await userEvent.click(screen.getByRole('button', { name: 'Photo 2 again' }))
    await waitFor(() => expect(screen.getByTestId('capture-progress')).toHaveTextContent('Photo 2 of 2'))
    await oneShot()
    expect(booth.state().expected_captures).toBe(2)
    expect(booth.state().frame_id).toBe('f34')
    const last = sent.at(-1)
    expect(last?.fields.shot_index).toBe('2')
    expect(last?.fields.attempt_no).toBe('2') // the new attempt, not the replaced one
  })

  it('offers only what the event allows: no retakes at all, or the whole set', async () => {
    const booth = server(visit({ expected_captures: 1, retake_mode: 'none' }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    await screen.findByText('All photos taken')
    expect(screen.queryByRole('button', { name: /again/ })).toBeNull()
  })

  it('takes the whole set again when the event retakes all photos together', async () => {
    const booth = server(visit({ expected_captures: 2, retake_mode: 'all' }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    await oneShot()
    await screen.findByText('All photos taken')
    expect(screen.queryByRole('button', { name: 'Photo 1 again' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Take all the photos again' }))
    await waitFor(() => expect(screen.getByTestId('capture-progress')).toHaveTextContent('Photo 1 of 2'))
  })

  it('a blocked camera explains itself and can be tried again', async () => {
    camera.failWith = new CameraError('denied', 'The camera is blocked for this booth.')
    const booth = server(visit({ expected_captures: 1 }))
    renderCapture(booth.handler)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The camera is blocked for this booth')
    expect(screen.getByTestId('capture-progress')).toHaveTextContent('Photo 1 of 1')

    camera.failWith = null
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(camera.opened).toBe(2)
    await oneShot()
    expect(await screen.findByText('All photos taken')).toBeInTheDocument()
  })

  it('a missing camera never leaves the booth on a blank screen', async () => {
    camera.failWith = new CameraError('missing', 'No camera is connected to this booth.')
    renderCapture(server().handler)
    expect(await screen.findByRole('alert')).toHaveTextContent('No camera is connected')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start over' })).toBeInTheDocument()
  })

  it('a camera unplugged mid-session is reported instead of sending nothing', async () => {
    const booth = server(visit({ expected_captures: 2 }))
    const { sent } = renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    camera.alive = false
    await oneShot()
    expect(await screen.findByRole('alert')).toHaveTextContent('The camera was disconnected')
    expect(sent).toHaveLength(0) // nothing was invented to fill the shot
    expect(screen.getByTestId('capture-progress')).toHaveTextContent('Photo 1 of 2')
  })

  it('a photo that does not reach the booth can be sent again under the same key', async () => {
    const booth = server(visit({ expected_captures: 1 }))
    let fail = true
    const { sent } = renderCapture(async (path, init) => {
      if (path.endsWith('/captures') && fail) {
        fail = false
        return json({ detail: 'network' }, 500)
      }
      return booth.handler(path, init)
    })
    await screen.findByTestId('capture-progress')
    await oneShot()
    expect(await screen.findByRole('alert')).toHaveTextContent('That photo did not reach the booth')

    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await oneShot()
    await screen.findByText('All photos taken')
    expect(sent).toHaveLength(2)
    // The same photo of the same attempt keeps its key, so the server counts it once.
    expect(sent[0]?.fields.idempotency_key).toBe(sent[1]?.fields.idempotency_key)
  })

  it('continues where the visit stood after a reload, never repeating a photo', async () => {
    const booth = server(visit({ expected_captures: 6, taken: 4 }))
    const { sent } = renderCapture(booth.handler)
    expect(await screen.findByTestId('capture-progress')).toHaveTextContent('Photo 5 of 6')
    await oneShot()
    await oneShot()
    expect(await screen.findByText('All photos taken')).toBeInTheDocument()
    expect(sent.map((call) => call.fields.shot_index)).toEqual(['5', '6'])
  })

  it('goes back to the frames when this browser has no visit', async () => {
    renderCapture(async (path) => (path === '/api/booth/frames' ? json(MENU) : json(null)))
    expect(await screen.findByText('the frame screen')).toBeInTheDocument()
  })

  it('stopping ends the visit and returns to the start screen', async () => {
    const booth = server(visit({ expected_captures: 2 }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await userEvent.click(screen.getByRole('button', { name: 'Stop and start over' }))
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
    expect(booth.state().state).toBe('cancelled')
    expect(camera.stopped).toBeGreaterThan(0) // the camera light goes out
  })

  it('finishing hands the photos to the decorate screen', async () => {
    const booth = server(visit({ expected_captures: 1 }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    await userEvent.click(await screen.findByRole('button', { name: 'These are good' }))
    await waitFor(() => expect(booth.state().state).toBe('reviewing'))
    expect(await screen.findByText('the decorate screen')).toBeInTheDocument()
  })

  it('a double tap on "These are good" finishes the visit once', async () => {
    const booth = server(visit({ expected_captures: 1 }))
    let finishes = 0
    renderCapture(async (path, init) => {
      if (path.endsWith('/finish')) finishes += 1
      return booth.handler(path, init)
    })
    await screen.findByTestId('capture-progress')
    await oneShot()
    const done = await screen.findByRole('button', { name: 'These are good' })
    act(() => {
      fireEvent.click(done)
      fireEvent.click(done) // the second tap, in the same frame
    })
    expect(await screen.findByText('the decorate screen')).toBeInTheDocument()
    expect(finishes).toBe(1)
  })

  it('a reload after the photos were taken goes straight to decorating', async () => {
    const booth = server(visit({ expected_captures: 2, taken: 2, state: 'reviewing' }))
    renderCapture(booth.handler)
    expect(await screen.findByText('the decorate screen')).toBeInTheDocument()
    expect(camera.opened).toBeLessThanOrEqual(1)
  })

  it('a lost answer is retried with the very same photo, never a new one (P67-002)', async () => {
    const booth = server(visit({ expected_captures: 1 }))
    let fail = true
    const { sent } = renderCapture(async (path, init) => {
      if (path.endsWith('/captures') && fail) {
        fail = false
        return json({ detail: 'the answer was lost' }, 500)
      }
      return booth.handler(path, init)
    })
    await screen.findByTestId('capture-progress')
    await oneShot()
    expect(await screen.findByRole('alert')).toHaveTextContent('That photo did not reach the booth')

    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await oneShot()
    await screen.findByText('All photos taken')
    expect(sent).toHaveLength(2)
    expect(sent[0]?.bytes).toBe(sent[1]?.bytes) // the same picture, not a second one
    expect(sent[0]?.fields.idempotency_key).toBe(sent[1]?.fields.idempotency_key)
    expect(camera.photos).toBe(1) // the camera was asked once
  })

  it('a photo the visit has moved past is dropped instead of being retried forever', async () => {
    const booth = server(visit({ expected_captures: 2 }))
    const { sent } = renderCapture(async (path, init) => {
      if (path.endsWith('/captures') && sent.length === 1) {
        return json({ detail: 'this idempotency key was used for a different request' }, 422)
      }
      return booth.handler(path, init)
    })
    await screen.findByTestId('capture-progress')
    await oneShot()
    await oneShot()
    await waitFor(() => expect(sent.length).toBeGreaterThanOrEqual(2))
    // The refused photo is not sent again under its old key.
    expect(new Set(sent.map((call) => call.fields.idempotency_key)).size).toBe(sent.length)
  })

  it('a camera that comes back carries on with the session (P67-003)', async () => {
    const booth = server(visit({ expected_captures: 2 }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    expect(screen.getByTestId('capture-progress')).toHaveTextContent('Photo 2 of 2')

    // Unplugged while the booth waits for the next photo.
    camera.alive = false
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('The camera was disconnected')

    camera.alive = true
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    await oneShot()
    expect(await screen.findByText('All photos taken')).toBeInTheDocument()
  })

  it('an unattended booth ends the visit and goes back to the start screen (P67-004)', async () => {
    const booth = server(visit({ expected_captures: 6, inactivity_timeout_s: 20 }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot() // somebody was there a moment ago

    await act(async () => {
      vi.advanceTimersByTime(21_000)
    })
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
    await waitFor(() => expect(booth.state().state).toBe('cancelled'))
    expect(camera.stopped).toBeGreaterThan(0) // the camera light goes out
  })

  it('the camera stops and a way out remains once the photos are done (P67-005)', async () => {
    const booth = server(visit({ expected_captures: 1, retake_mode: 'none' }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    expect(screen.queryByRole('button', { name: /again/ })).toBeNull() // this event allows none
    await userEvent.click(await screen.findByRole('button', { name: 'These are good' }))
    await waitFor(() => expect(booth.state().state).toBe('reviewing'))
    expect(camera.stopped).toBeGreaterThan(0) // the camera light goes out with the last photo
    expect(await screen.findByText('the decorate screen')).toBeInTheDocument()
  })

  it('a second tap on a retake can not throw away the new photo (P67-006)', async () => {
    const booth = server(visit({ expected_captures: 2, retake_mode: 'per_photo' }))
    const asked: unknown[] = []
    let release = () => {}
    renderCapture(async (path, init) => {
      if (path.endsWith('/retake')) {
        asked.push(JSON.parse(String(init?.body)))
        await new Promise<void>((resolve) => {
          release = resolve
        })
      }
      return booth.handler(path, init)
    })
    await screen.findByTestId('capture-progress')
    await oneShot()
    await oneShot()
    await screen.findByText('All photos taken')

    const again = screen.getByRole('button', { name: 'Photo 2 again' })
    await userEvent.click(again)
    await userEvent.click(again) // the double tap
    expect(asked).toHaveLength(1) // the second one never left the booth
    expect(asked[0]).toMatchObject({ shot_index: 2, state_version: expect.any(Number) })
    await act(async () => {
      release()
      await Promise.resolve()
    })
  })

  it('uses the camera the booth was told to use, and offers no picker of its own', async () => {
    camera.cameras = [
      { id: 'built-in', label: 'Built-in camera' },
      { id: 'usb', label: 'Event camera' },
    ]
    localStorage.setItem('pb.booth.cameraDevice', 'usb')
    const booth = server(visit({ expected_captures: 2 }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    // Which camera to use is settled on the Admin test page; this screen only takes photos.
    await waitFor(() => expect(camera.openedWith.at(-1)).toBe('usb'))
    expect(screen.queryByLabelText('Camera')).toBeNull()
    await oneShot()
    expect(camera.photos).toBeGreaterThan(0)
    await oneShot()
    await screen.findByText('All photos taken')
    expect(screen.queryByLabelText('Camera')).toBeNull() // nor on the review screen
  })

  it.each(LAYOUTS)(
    'shows the camera in the shape $label keeps of one photo',
    async (layout) => {
      const booth = server(
        visit({
          expected_captures: layout.captures,
          frame_id: layout.id,
          template_key: layout.key,
          layout_label: layout.label,
        }),
      )
      renderCapture(booth.handler)
      const frame = await screen.findByTestId('photo-frame')
      // Each size keeps a different shape of each photo; the booth frames the participant in it.
      expect(frame.style.getPropertyValue('--pb-slot-w')).toBe(String(layout.slot.width))
      expect(frame.style.getPropertyValue('--pb-slot-h')).toBe(String(layout.slot.height))
      expect(within(frame).getByLabelText('Camera preview')).toBeInTheDocument()
      // The countdown is drawn over that same picture, not beside it.
      await act(async () => {
        vi.advanceTimersByTime(500)
      })
      expect(within(frame).getByTestId('countdown')).toBeInTheDocument()
    },
  )

  it('shows every photo it has taken, each under its own number', async () => {
    const booth = server(visit({ expected_captures: 4 }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    const places = () => screen.getAllByTestId('captured-photo')
    // One place per shot from the start, all of them empty.
    expect(places()).toHaveLength(4)
    expect(screen.queryAllByRole('img')).toHaveLength(0)
    for (const index of [1, 2, 3, 4]) {
      expect(within(places()[index - 1] as HTMLElement).getByText(`Photo ${index}`)).toBeInTheDocument()
    }

    await oneShot()
    // Only the first place has a picture, and it is that shot's own photo.
    const first = within(places()[0] as HTMLElement).getByRole('img')
    expect(first).toHaveAttribute('src', expect.stringContaining('capture-1-1'))
    expect(first).toHaveAccessibleName('Photo 1')
    expect(screen.getAllByRole('img')).toHaveLength(1) // the others are still empty

    await oneShot()
    const second = within(places()[1] as HTMLElement).getByRole('img')
    expect(second).toHaveAttribute('src', expect.stringContaining('capture-2-1'))
    expect(new Set(screen.getAllByRole('img').map((img) => img.getAttribute('src'))).size).toBe(2)
  })

  it('opens the photo of the thumbnail that was pressed, and closes without touching the camera', async () => {
    const booth = server(visit({ expected_captures: 4 }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    await oneShot()
    const opened = camera.opened

    await userEvent.click(screen.getByRole('button', { name: 'Photo 2, see it bigger' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: 'Photo 2' })).toBeInTheDocument()
    expect(within(dialog).getByTestId('photo-large')).toHaveAttribute(
      'src',
      expect.stringContaining('capture-2-1'),
    )
    expect(within(dialog).getByRole('button', { name: 'Close' })).toHaveFocus()
    // Looking at a photo neither starts another camera nor stops this one.
    expect(camera.opened).toBe(opened)
    expect(camera.stopped).toBe(0)

    await userEvent.tab()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: 'Photo 2, see it bigger' })).toHaveFocus()
  })

  it('a retaken photo replaces only its own thumbnail', async () => {
    const booth = server(visit({ expected_captures: 2, retake_mode: 'per_photo' }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    await oneShot()
    const before = thumbnails().map((img) => img.getAttribute('src'))
    expect(before).toHaveLength(2)

    await userEvent.click(screen.getByRole('button', { name: 'Photo 2 again' }))
    await waitFor(() => expect(thumbnails()).toHaveLength(1)) // photo 2 is gone
    expect(thumbnails()[0]).toHaveAttribute('src', before[0] as string)
    await oneShot()
    const after = thumbnails().map((img) => img.getAttribute('src'))
    expect(after[0]).toBe(before[0]) // photo 1 untouched
    expect(after[1]).not.toBe(before[1]) // photo 2 is the new one
    expect(after[1]).toContain('capture-2-2')
  })

  it('the review shows the frame, the layout and every photo in order', async () => {
    const booth = server(visit({ expected_captures: 2, retake_mode: 'none' }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    await oneShot()
    await screen.findByText('All photos taken')
    expect(screen.getByText('Gold frame · 3×4 · 2 photos')).toBeInTheDocument()
    expect(thumbnails().map((img) => img.getAttribute('alt'))).toEqual(['Photo 1', 'Photo 2'])
    expect(screen.queryByRole('button', { name: /again/ })).toBeNull() // this event allows none
  })

  it('the review shows a photo that was taken, never the live camera', async () => {
    const booth = server(visit({ expected_captures: 2, retake_mode: 'none' }))
    renderCapture(booth.handler)
    await screen.findByTestId('capture-progress')
    await oneShot()
    await oneShot()
    await screen.findByText('All photos taken')

    // The picture in the photo's own shape is a stored capture; the camera is not on screen.
    const frame = screen.getByTestId('photo-frame')
    expect(within(frame).queryByLabelText('Camera preview')).toBeNull()
    const big = within(frame).getByTestId('review-photo')
    expect(big).toHaveAttribute('src', expect.stringContaining('capture-1-1'))
    expect(frame.style.getPropertyValue('--pb-slot-w')).toBe('810')

    // Pressing a place shows that photo, and pressing the big one opens the full dialog.
    await userEvent.click(screen.getByRole('button', { name: 'Show photo 2' }))
    await waitFor(() =>
      expect(screen.getByTestId('review-photo')).toHaveAttribute(
        'src',
        expect.stringContaining('capture-2-1'),
      ),
    )
    expect(screen.getByRole('button', { name: 'Show photo 2' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Photo 2, see it bigger' }))
    expect(within(screen.getByRole('dialog')).getByRole('heading', { name: 'Photo 2' })).toBeInTheDocument()
  })

  it('the booth screens say nothing about tests when a guest is using them', async () => {
    renderCapture(server(visit({ expected_captures: 2 })).handler)
    await screen.findByTestId('capture-progress')
    expect(screen.queryByText(/TEST/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Exit test' })).toBeNull()
  })

  it('takes the whole display, like the booth it is', async () => {
    renderCapture(server(visit({ expected_captures: 2 })).handler)
    await screen.findByTestId('capture-progress')
    expect(screen.getByTestId('booth-shell')).toBeInTheDocument()
    expect(document.documentElement).toHaveAttribute('data-booth-immersive')
  })
})