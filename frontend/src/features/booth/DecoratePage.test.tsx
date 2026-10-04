import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'

import { ApiClientProvider } from '../../shared/api/ApiClientContext'
import {
  createApiClient,
  type BoothSessionState,
  type DecorateLayout,
  type DecorationCatalog,
  type FrameMenu,
} from '../../shared/api/client'
import { DecoratePage } from './DecoratePage'
import { LEAVE_DEADLINE_MS } from './kiosk'

/**
 * Decorating: the photos drawn as the server will compose them, a filter and stickers with undo
 * and start-again, a confirmation, then the finished photos are made exactly once with the
 * guest's decoration.
 */

const SESSION_ID = '44444444-4444-4444-8444-444444444444'

function visit(overrides: Partial<BoothSessionState> = {}): BoothSessionState {
  return {
    id: SESSION_ID,
    is_test: false,
    state: 'reviewing',
    state_version: 4,
    countdown_seconds: 3,
    mirror: true,
    retake_mode: 'per_photo',
    inactivity_timeout_s: 60,
    expected_captures: 6,
    taken: 6,
    template_key: 'strip_2x6',
    layout_label: '2×6',
    frame_id: 'fs',
    shots: [],
    outputs: [],
    ...overrides,
  }
}

const slot = (n: number, y: number) => ({
  capture_id: `cap-${n}`,
  shot_index: n,
  version: `v${n}`,
  x: 30,
  y,
  width: 540,
  height: 405,
})

const LAYOUT: DecorateLayout = {
  mirror: true,
  frame_url: `/api/booth/sessions/${SESSION_ID}/frame.png?v=f1`,
  outputs: [
    { output_index: 1, width: 600, height: 1800, slots: [slot(1, 30), slot(2, 465), slot(3, 900)] },
    { output_index: 2, width: 600, height: 1800, slots: [slot(4, 30), slot(5, 465), slot(6, 900)] },
  ],
}

const CATALOG: DecorationCatalog = {
  filters: [
    { key: 'none', label: 'Original', matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0] },
    {
      key: 'sepia',
      label: 'Sepia',
      matrix: [0.393, 0.769, 0.189, 0, 0.349, 0.686, 0.168, 0, 0.272, 0.534, 0.131, 0],
    },
  ],
  stickers: [
    { key: 'heart', label: 'Heart', url: '/api/booth/decorations/stickers/heart.png?v=1', width: 400, height: 360 },
    { key: 'star', label: 'Star', url: '/api/booth/decorations/stickers/star.png?v=1', width: 480, height: 460 },
  ],
  max_stickers_per_photo: 2,
}

const MENU: FrameMenu = {
  frames: [],
  layouts: [],
  allow_surprise_me: false,
  theme: { background: '#101418', heading: '#FFFFFF', primary_bg: '#AA3311', primary_text: '#FFFFFF' },
  start_screen: { start_button_text: 'Start', logo_url: null, background_url: null },
  countdown_seconds: 3,
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

interface Booth {
  renders: { idempotency_key: string; decoration?: unknown }[]
  reads: number
  gaveUp: number
  current: BoothSessionState
}

function server(
  start: BoothSessionState,
  { busyFirst = 0, failRender = false } = {},
): { booth: Booth; fetcher: (path: string, init?: RequestInit) => Promise<Response> } {
  const booth: Booth = { renders: [], reads: 0, gaveUp: 0, current: start }
  let busy = busyFirst
  const fetcher = async (path: string, init?: RequestInit): Promise<Response> => {
    if (path === '/api/booth/frames') return json(MENU)
    if (path === '/api/booth/decorations') return json(CATALOG)
    if (path === '/api/booth/sessions/current') return json(booth.current)
    if (path === `/api/booth/sessions/${SESSION_ID}/decorate`) return json(LAYOUT)
    if (path === `/api/booth/sessions/${SESSION_ID}`) {
      booth.reads += 1
      return json(booth.current)
    }
    if (path.endsWith('/render')) {
      booth.renders.push(JSON.parse(String(init?.body)) as Booth['renders'][number])
      if (busy > 0) {
        busy -= 1
        return json({ detail: 'busy' }, 503)
      }
      if (failRender) return json({ detail: 'the photos could not be made' }, 409)
      booth.current = { ...booth.current, state: 'delivered' }
      return json(booth.current)
    }
    if (path.endsWith('/give-up')) {
      booth.gaveUp += 1
      booth.current = { ...booth.current, state: 'cancelled' }
      return json(booth.current)
    }
    return json({ detail: `unexpected ${path}` }, 500)
  }
  return { booth, fetcher }
}

function renderDecorate(fetcher: (path: string, init?: RequestInit) => Promise<Response>): void {
  const keys = { get: () => 'k'.repeat(43), set: () => undefined, clear: () => undefined }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ApiClientProvider client={createApiClient(fetcher, keys)}>
        <MemoryRouter initialEntries={['/booth/decorate']}>
          <Routes>
            <Route path="/booth/decorate" element={<DecoratePage />} />
            <Route path="/booth/done" element={<p>the take-home screen</p>} />
            <Route path="/booth/capture" element={<p>the camera screen</p>} />
            <Route path="/booth" element={<p>the start screen</p>} />
          </Routes>
        </MemoryRouter>
      </ApiClientProvider>
    </QueryClientProvider>,
  )
}

/** jsdom has no SVG geometry: the screen maps one to one onto the photo's own pixels. */
async function withGeometry(run: () => Promise<void>): Promise<void> {
  class Point {
    constructor(
      readonly x: number,
      readonly y: number,
    ) {}
    matrixTransform() {
      return { x: this.x, y: this.y }
    }
  }
  vi.stubGlobal('DOMPoint', Point)
  Object.defineProperty(SVGSVGElement.prototype, 'getScreenCTM', {
    configurable: true,
    value: () => ({ inverse: () => ({}) }),
  })
  try {
    await run()
  } finally {
    vi.unstubAllGlobals()
    Reflect.deleteProperty(SVGSVGElement.prototype, 'getScreenCTM')
  }
}

async function ready(): Promise<{ first: HTMLElement; second: HTMLElement }> {
  await screen.findByRole('heading', { name: 'Decorate your photos' })
  const [first, second] = screen.getAllByTestId('decorated-photo')
  if (!first || !second) throw new Error('both strips are drawn')
  return { first, second }
}

async function finish(): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: 'Finish' }))
  const dialog = screen.getByRole('dialog', { name: 'Finish your photos?' })
  await userEvent.click(within(dialog).getByRole('button', { name: 'Make my photos' }))
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('DecoratePage (decorating the finished photos)', () => {
  it('draws each photo as the server will compose it: slots, mirror, frame on top', async () => {
    const { fetcher } = server(visit())
    renderDecorate(fetcher)
    const { first, second } = await ready()
    expect(screen.getByTestId('booth-shell')).toBeInTheDocument()
    expect(first).toHaveAttribute('viewBox', '0 0 600 1800')
    const images = [...first.querySelectorAll('image')].map((node) => node.getAttribute('href'))
    expect(images).toEqual([
      `/api/booth/sessions/${SESSION_ID}/captures/cap-1.jpg?v=v1`,
      `/api/booth/sessions/${SESSION_ID}/captures/cap-2.jpg?v=v2`,
      `/api/booth/sessions/${SESSION_ID}/captures/cap-3.jpg?v=v3`,
      LAYOUT.frame_url, // the frame lies over the photos, unchanged
    ])
    const photo = first.querySelector('image')
    expect(photo).toHaveAttribute('preserveAspectRatio', 'xMidYMid slice') // the server's crop
    expect(photo).toHaveAttribute('transform', 'translate(600 0) scale(-1 1)') // mirrored
    expect(second.querySelector('image')?.getAttribute('href')).toContain('cap-4.jpg')
    expect(first.querySelector('filter')).toBeNull() // no filter yet
  })

  it('a filter colours the photos with the very matrix the server applies', async () => {
    const { fetcher } = server(visit())
    renderDecorate(fetcher)
    const { first } = await ready()
    await userEvent.click(screen.getByRole('tab', { name: 'Filters' }))
    await userEvent.click(screen.getByRole('radio', { name: /Sepia/ }))
    expect(screen.getByRole('radio', { name: /Sepia/ })).toHaveAttribute('aria-checked', 'true')
    const filter = first.querySelector('filter')
    expect(filter).toHaveAttribute('color-interpolation-filters', 'sRGB')
    expect(filter?.querySelector('feColorMatrix')).toHaveAttribute(
      'values',
      '0.393 0.769 0.189 0 0 0.349 0.686 0.168 0 0 0.272 0.534 0.131 0 0 0 0 0 1 0',
    )
  })

  it('adds stickers to the chosen photo, with undo and start again', async () => {
    const { fetcher } = server(visit())
    renderDecorate(fetcher)
    const { first, second } = await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
    expect(within(first).getAllByTestId('placed-sticker')).toHaveLength(1)
    expect(within(first).getByTestId('placed-sticker')).toHaveAttribute('data-selected')

    // Tapping the second strip makes it the one new stickers go on.
    fireEvent.pointerDown(second)
    await userEvent.click(screen.getByRole('button', { name: 'Add Star' }))
    expect(within(second).getAllByTestId('placed-sticker')).toHaveLength(1)

    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(within(second).queryAllByTestId('placed-sticker')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Start again' }))
    expect(screen.queryAllByTestId('placed-sticker')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(within(first).getAllByTestId('placed-sticker')).toHaveLength(1)
  })

  it('a tapped sticker goes on the chosen photo, chosen, with its handles on its corners', async () => {
    const { fetcher } = server(visit())
    renderDecorate(fetcher)
    const { first, second } = await ready()
    expect(screen.queryByTestId('sticker-handles')).toBeNull() // nothing chosen yet
    expect(screen.queryByRole('group', { name: 'Chosen sticker' })).toBeNull() // no button panel
    await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
    const handles = within(first).getByTestId('sticker-handles')
    expect(within(first).getByTestId('placed-sticker')).toHaveAttribute('data-selected')
    expect(within(first).getByTestId('sticker-outline')).toBeInTheDocument()
    // Heart: 0.32 of 600 wide (192), 360/400 as tall (172.8), centred at (300, 900).
    const spot = (name: string) =>
      within(handles).getByRole('button', { name }).getAttribute('transform')
    expect(spot('Move sticker')).toBe('translate(204 813.6)')
    expect(spot('Remove sticker')).toBe('translate(396 813.6)')
    expect(spot('Resize sticker')).toBe('translate(396 986.4)')

    // The other strip is decorated on its own: its sticker, its handles.
    fireEvent.pointerDown(second)
    await userEvent.click(screen.getByRole('button', { name: 'Add Star' }))
    expect(within(second).getByTestId('sticker-handles')).toBeInTheDocument()
    expect(within(first).queryByTestId('sticker-handles')).toBeNull()
    expect(within(first).getAllByTestId('placed-sticker')).toHaveLength(1)
  })

  describe.each(['mouse', 'touch', 'pen'])('with a %s', (pointerType) => {
    it('dragging Resize scales the sticker in place, keeping its shape, as one undo step', async () => {
      await withGeometry(async () => {
        const { booth, fetcher } = server(visit())
        renderDecorate(fetcher)
        const { first } = await ready()
        await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
        const resize = within(first).getByRole('button', { name: 'Resize sticker' })
        fireEvent.pointerDown(resize, { pointerId: 4, pointerType, clientX: 396, clientY: 986.4 })
        // Twice as far from the sticker's centre (300, 900): twice the size.
        fireEvent.pointerMove(first, { pointerId: 4, pointerType, clientX: 492, clientY: 1072.8 })
        fireEvent.pointerUp(first, { pointerId: 4, pointerType })
        const heart = within(first).getByTestId('placed-sticker')
        expect(heart).toHaveAttribute('transform', 'translate(300 900) rotate(0)') // in place
        const image = heart.querySelector('image')
        expect(Number(image?.getAttribute('width'))).toBeCloseTo(384)
        expect(Number(image?.getAttribute('height'))).toBeCloseTo(345.6) // the same shape
        await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
        expect(Number(heart.querySelector('image')?.getAttribute('width'))).toBeCloseTo(192)
        await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
        expect(within(first).queryAllByTestId('placed-sticker')).toHaveLength(0)
        expect(booth.renders).toHaveLength(0)
      })
    })

    it('dragging the Move handle or the sticker itself moves it', async () => {
      await withGeometry(async () => {
        const { fetcher } = server(visit())
        renderDecorate(fetcher)
        const { first } = await ready()
        await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
        const move = within(first).getByRole('button', { name: 'Move sticker' })
        fireEvent.pointerDown(move, { pointerId: 5, pointerType, clientX: 204, clientY: 813.6 })
        fireEvent.pointerMove(first, { pointerId: 5, pointerType, clientX: 234, clientY: 913.6 })
        fireEvent.pointerUp(first, { pointerId: 5, pointerType })
        const heart = within(first).getByTestId('placed-sticker')
        expect(heart).toHaveAttribute('transform', 'translate(330 1000) rotate(0)')
        fireEvent.pointerDown(heart, { pointerId: 6, pointerType, clientX: 330, clientY: 1000 })
        fireEvent.pointerMove(first, { pointerId: 6, pointerType, clientX: 300, clientY: 1100 })
        fireEvent.pointerUp(first, { pointerId: 6, pointerType })
        expect(heart).toHaveAttribute('transform', 'translate(300 1100) rotate(0)')
        // The handles came along, still on the corners.
        expect(
          within(first).getByRole('button', { name: 'Move sticker' }).getAttribute('transform'),
        ).toBe('translate(204 1013.6)')
      })
    })

    it('Remove deletes the sticker at once, and Undo brings it back', async () => {
      const { fetcher } = server(visit())
      renderDecorate(fetcher)
      const { first } = await ready()
      await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
      fireEvent.pointerDown(within(first).getByRole('button', { name: 'Remove sticker' }), {
        pointerId: 8,
        pointerType,
      })
      expect(within(first).queryAllByTestId('placed-sticker')).toHaveLength(0)
      expect(screen.queryByTestId('sticker-handles')).toBeNull()
      await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
      expect(within(first).getAllByTestId('placed-sticker')).toHaveLength(1)
    })
  })

  it('a second finger during a resize is ignored, whichever lifts first (review R2)', async () => {
    await withGeometry(async () => {
      const { fetcher } = server(visit())
      renderDecorate(fetcher)
      const { first } = await ready()
      await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
      const heart = within(first).getByTestId('placed-sticker')
      const width = () => Number(heart.querySelector('image')?.getAttribute('width'))
      const resize = within(first).getByRole('button', { name: 'Resize sticker' })
      fireEvent.pointerDown(resize, { pointerId: 1, pointerType: 'touch', clientX: 396, clientY: 986.4 })
      fireEvent.pointerMove(first, { pointerId: 1, pointerType: 'touch', clientX: 492, clientY: 1072.8 })
      expect(width()).toBeCloseTo(384)
      // Another finger lands on the sticker and moves to its centre: nothing changes.
      fireEvent.pointerDown(heart, { pointerId: 2, pointerType: 'touch', clientX: 320, clientY: 920 })
      fireEvent.pointerMove(first, { pointerId: 2, pointerType: 'touch', clientX: 300, clientY: 900 })
      expect(width()).toBeCloseTo(384)
      expect(heart).toHaveAttribute('transform', 'translate(300 900) rotate(0)')
      // The other finger lifts first: the resize goes on with the first one.
      fireEvent.pointerUp(first, { pointerId: 2, pointerType: 'touch' })
      fireEvent.pointerMove(first, { pointerId: 1, pointerType: 'touch', clientX: 444, clientY: 1029.6 })
      expect(width()).toBeCloseTo(288)
      fireEvent.pointerUp(first, { pointerId: 1, pointerType: 'touch' })
      // One undo step for the whole resize.
      await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
      expect(width()).toBeCloseTo(192)
    })
  })

  it('when the resizing finger lifts first, the resize ends and the other finger changes nothing', async () => {
    await withGeometry(async () => {
      const { fetcher } = server(visit())
      renderDecorate(fetcher)
      const { first } = await ready()
      await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
      const heart = within(first).getByTestId('placed-sticker')
      const width = () => Number(heart.querySelector('image')?.getAttribute('width'))
      const resize = within(first).getByRole('button', { name: 'Resize sticker' })
      fireEvent.pointerDown(resize, { pointerId: 1, pointerType: 'pen', clientX: 396, clientY: 986.4 })
      fireEvent.pointerMove(first, { pointerId: 1, pointerType: 'pen', clientX: 492, clientY: 1072.8 })
      fireEvent.pointerDown(heart, { pointerId: 2, pointerType: 'touch', clientX: 320, clientY: 920 })
      fireEvent.pointerUp(first, { pointerId: 1, pointerType: 'pen' })
      expect(width()).toBeCloseTo(384)
      fireEvent.pointerMove(first, { pointerId: 2, pointerType: 'touch', clientX: 100, clientY: 100 })
      fireEvent.pointerUp(first, { pointerId: 2, pointerType: 'touch' })
      expect(width()).toBeCloseTo(384)
      expect(heart).toHaveAttribute('transform', 'translate(300 900) rotate(0)')
      // A new gesture starts normally afterwards.
      fireEvent.pointerDown(heart, { pointerId: 3, pointerType: 'mouse', clientX: 300, clientY: 900 })
      fireEvent.pointerMove(first, { pointerId: 3, pointerType: 'mouse', clientX: 375, clientY: 1125 })
      fireEvent.pointerUp(first, { pointerId: 3, pointerType: 'mouse' })
      expect(heart).toHaveAttribute('transform', 'translate(375 1125) rotate(0)')
    })
  })

  it('the Remove handle also works from the keyboard', async () => {
    const { fetcher } = server(visit())
    renderDecorate(fetcher)
    const { first } = await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
    within(first).getByRole('button', { name: 'Remove sticker' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(within(first).queryAllByTestId('placed-sticker')).toHaveLength(0)
  })

  it('near the edge of the photo the handles stay on it, within reach', async () => {
    await withGeometry(async () => {
      const { fetcher } = server(visit())
      renderDecorate(fetcher)
      const { first } = await ready()
      await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
      const heart = within(first).getByTestId('placed-sticker')
      fireEvent.pointerDown(heart, { pointerId: 9, clientX: 300, clientY: 900 })
      fireEvent.pointerMove(first, { pointerId: 9, clientX: -400, clientY: -1000 }) // off the top left
      fireEvent.pointerUp(first, { pointerId: 9 })
      expect(heart).toHaveAttribute('transform', 'translate(0 0) rotate(0)') // centre on the corner
      for (const name of ['Move sticker', 'Remove sticker', 'Resize sticker']) {
        const [x, y] = (
          within(first).getByRole('button', { name }).getAttribute('transform') ?? ''
        )
          .replace(/[^\d. -]/g, '')
          .trim()
          .split(/\s+/)
          .map(Number)
        expect(x, name).toBeGreaterThanOrEqual(24) // a whole handle (radius 24) on the photo
        expect(y, name).toBeGreaterThanOrEqual(24)
      }
    })
  })

  it('the handles are never part of what is made: frozen for confirmation, never sent', async () => {
    const { booth, fetcher } = server(visit())
    renderDecorate(fetcher)
    const { first } = await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
    expect(within(first).getByTestId('sticker-handles')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Finish' }))
    expect(screen.getByRole('dialog', { name: 'Finish your photos?' })).toBeInTheDocument()
    expect(screen.queryByTestId('sticker-handles')).toBeNull()
    expect(screen.queryByTestId('sticker-outline')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Make my photos' }))
    expect(await screen.findByText('the take-home screen')).toBeInTheDocument()
    expect(booth.renders[0]?.decoration).toEqual({
      filter: 'none',
      stickers: [{ sticker: 'heart', output: 1, x: 0.5, y: 0.5, size: 0.32, rotation: 0 }],
    })
  })
  it('offers no more stickers than a photo takes', async () => {
    const { fetcher } = server(visit())
    renderDecorate(fetcher)
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add Star' }))
    expect(screen.getByRole('button', { name: 'Add Heart' })).toBeDisabled()
    expect(screen.getByText(/all the stickers it can take/)).toBeInTheDocument()
  })

  it('asks first, then makes the photos once with the decoration, and shows them', async () => {
    const { booth, fetcher } = server(visit(), { busyFirst: 2 })
    renderDecorate(fetcher)
    await ready()
    await userEvent.click(screen.getByRole('tab', { name: 'Filters' }))
    await userEvent.click(screen.getByRole('radio', { name: /Sepia/ }))
    await userEvent.click(screen.getByRole('tab', { name: 'Stickers' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))

    // "Keep decorating" changes nothing and makes nothing.
    await userEvent.click(screen.getByRole('button', { name: 'Finish' }))
    await userEvent.click(screen.getByRole('button', { name: 'Keep decorating' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(booth.renders).toHaveLength(0)

    await finish()
    expect(await screen.findByTestId('making-photos')).toHaveTextContent('Making your photos')
    await act(async () => {
      vi.advanceTimersByTime(1600)
    })
    await act(async () => {
      vi.advanceTimersByTime(1600)
    })
    expect(await screen.findByText('the take-home screen')).toBeInTheDocument()
    expect(booth.renders).toHaveLength(3) // the busy worker was asked again...
    expect(new Set(booth.renders.map((r) => r.idempotency_key)).size).toBe(1) // ...with one key
    expect(booth.renders[0]?.decoration).toEqual({
      filter: 'sepia',
      stickers: [{ sticker: 'heart', output: 1, x: 0.5, y: 0.5, size: 0.32, rotation: 0 }],
    })
  })

  it('a guest who wants nothing just finishes', async () => {
    const { booth, fetcher } = server(visit())
    renderDecorate(fetcher)
    await ready()
    await finish()
    expect(await screen.findByText('the take-home screen')).toBeInTheDocument()
    expect(booth.renders[0]?.decoration).toEqual({ filter: 'none', stickers: [] })
  })

  it('two presses of "Make my photos" in the same frame make the photos once (P12-R4)', async () => {
    const { booth, fetcher } = server(visit())
    renderDecorate(fetcher)
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Finish' }))
    const make = within(screen.getByRole('dialog', { name: 'Finish your photos?' })).getByRole(
      'button',
      { name: 'Make my photos' },
    )
    act(() => {
      fireEvent.click(make)
      fireEvent.click(make)
    })
    expect(await screen.findByText('the take-home screen')).toBeInTheDocument()
    expect(booth.renders).toHaveLength(1)
  })

  it('starting over reaches the start even when the server never answers (P12-R1)', async () => {
    const { fetcher } = server(visit(), { failRender: true })
    let gaveUp = 0
    renderDecorate(async (path, init) => {
      if (path.endsWith('/give-up')) {
        gaveUp += 1
        return new Promise<Response>(() => undefined)
      }
      return fetcher(path, init)
    })
    await ready()
    await finish()
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be made')
    const over = screen.getByRole('button', { name: 'Start over' })
    act(() => {
      fireEvent.click(over)
      fireEvent.click(over)
    })
    await act(async () => {
      vi.advanceTimersByTime(LEAVE_DEADLINE_MS + 100)
    })
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
    expect(gaveUp).toBe(1)
  })

  it('says so when the photos can not be made, and starts over', async () => {
    const { booth, fetcher } = server(visit(), { failRender: true })
    renderDecorate(fetcher)
    await ready()
    await finish()
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be made')
    await userEvent.click(screen.getByRole('button', { name: 'Start over' }))
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
    expect(booth.gaveUp).toBe(1)
  })

  it('sends a visit that is already made, or still taking photos, where it belongs', async () => {
    const delivered = server(visit({ state: 'delivered' }))
    renderDecorate(delivered.fetcher)
    expect(await screen.findByText('the take-home screen')).toBeInTheDocument()
    expect(delivered.booth.renders).toHaveLength(0)
  })

  it('sends a visit still taking photos back to the camera', async () => {
    const { fetcher } = server(visit({ state: 'capturing', taken: 3 }))
    renderDecorate(fetcher)
    expect(await screen.findByText('the camera screen')).toBeInTheDocument()
  })

  it('keeps a busy guest’s visit alive and lets an empty booth go back to the start', async () => {
    const { booth, fetcher } = server(visit({ inactivity_timeout_s: 30 }))
    renderDecorate(fetcher)
    await ready()
    // Somebody is decorating: the server hears from the booth (every 10 s at most here).
    fireEvent.pointerDown(window)
    await act(async () => {
      vi.advanceTimersByTime(10_500)
    })
    await waitFor(() => expect(booth.reads).toBe(1))
    // Then nobody touches anything for the event's inactivity time.
    await act(async () => {
      vi.advanceTimersByTime(31_000)
    })
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
    await waitFor(() => expect(booth.gaveUp).toBe(1))
    expect(booth.reads).toBe(1) // nobody there: nothing kept the visit alive
  })

  it('confirms exactly what is on screen, even with a finger still on a sticker (P9-R1)', async () => {
    // jsdom has no SVG geometry: the screen maps one to one onto the photo's own pixels.
    class Point {
      constructor(
        readonly x: number,
        readonly y: number,
      ) {}
      matrixTransform() {
        return { x: this.x, y: this.y }
      }
    }
    vi.stubGlobal('DOMPoint', Point)
    Object.defineProperty(SVGSVGElement.prototype, 'getScreenCTM', {
      configurable: true,
      value: () => ({ inverse: () => ({}) }),
    })
    try {
      const { booth, fetcher } = server(visit())
      renderDecorate(fetcher)
      const { first } = await ready()
      await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
      const heart = within(first).getByTestId('placed-sticker')
      fireEvent.pointerDown(heart, { pointerId: 7, clientX: 300, clientY: 900 })
      fireEvent.pointerMove(first, { pointerId: 7, clientX: 360, clientY: 960 })
      expect(heart).toHaveAttribute('transform', 'translate(360 960) rotate(0)')
      // Still holding the sticker, the guest finishes from the keyboard.
      screen.getByRole('button', { name: 'Finish' }).focus()
      await userEvent.keyboard('{Enter}')
      expect(screen.getByRole('dialog', { name: 'Finish your photos?' })).toBeInTheDocument()
      // The finger goes on moving while the question is asked: nothing changes any more.
      fireEvent.pointerMove(first, { pointerId: 7, clientX: 100, clientY: 100 })
      expect(within(first).getByTestId('placed-sticker')).toHaveAttribute(
        'transform',
        'translate(360 960) rotate(0)',
      )
      const dialog = screen.getByRole('dialog', { name: 'Finish your photos?' })
      await userEvent.click(within(dialog).getByRole('button', { name: 'Make my photos' }))
      expect(await screen.findByText('the take-home screen')).toBeInTheDocument()
      expect(booth.renders[0]?.decoration).toEqual({
        filter: 'none',
        stickers: [{ sticker: 'heart', output: 1, x: 0.6, y: 0.5333, size: 0.32, rotation: 0 }],
      })
    } finally {
      vi.unstubAllGlobals()
      Reflect.deleteProperty(SVGSVGElement.prototype, 'getScreenCTM')
    }
  })

  it('a guest dragging stickers is somebody at the booth (P9-R4)', async () => {
    const { booth, fetcher } = server(visit({ inactivity_timeout_s: 30 }))
    renderDecorate(fetcher)
    const { first } = await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Add Heart' }))
    const heart = within(first).getByTestId('placed-sticker')
    for (let second = 0; second < 60; second += 10) {
      // The sticker stops its own pointer events; the booth still sees them.
      fireEvent.pointerDown(heart, { pointerId: 3 })
      fireEvent.pointerUp(first, { pointerId: 3 })
      await act(async () => {
        vi.advanceTimersByTime(10_000)
      })
    }
    expect(screen.getByRole('heading', { name: 'Decorate your photos' })).toBeInTheDocument()
    expect(booth.gaveUp).toBe(0)
    expect(booth.reads).toBeGreaterThanOrEqual(3) // and the server heard about it
  })

  it('tells the server at once when a guest comes back, and leaves a visit that ended (P9-R5)', async () => {
    const { booth, fetcher } = server(visit({ inactivity_timeout_s: 60 }))
    renderDecorate(fetcher)
    await ready()
    await act(async () => {
      vi.advanceTimersByTime(25_000) // a quiet spell longer than the 20 s keep-alive interval
    })
    expect(booth.reads).toBe(0)
    fireEvent.keyDown(window, { key: 'a' })
    await waitFor(() => expect(booth.reads).toBe(1)) // at once, not at the next tick
    // The visit was ended elsewhere meanwhile: the next touch finds out and leaves.
    booth.current = { ...booth.current, state: 'cancelled' }
    await act(async () => {
      vi.advanceTimersByTime(21_000)
    })
    fireEvent.keyDown(window, { key: 'b' })
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
  })
  it('wears the event theme', async () => {
    const { fetcher } = server(visit())
    renderDecorate(fetcher)
    await ready()
    const themed = screen.getByRole('group', { name: 'Decorate your photos' })
    expect(themed.style.getPropertyValue('--ev-primary-bg')).toBe('#AA3311')
  })
})
