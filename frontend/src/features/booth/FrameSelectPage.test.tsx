import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'

import { ApiClientProvider } from '../../shared/api/ApiClientContext'
import { createApiClient, type FrameMenu } from '../../shared/api/client'
import { FrameSelectPage, SESSION_FRAME_KEY } from './FrameSelectPage'

const PLAN_46 = {
  frame_id: 'f46',
  template_key: 'print_4x6',
  layout_label: '4×6',
  captures: 4,
  outputs: 1,
  photos_per_output: 4,
  output_capture_groups: [[1, 2, 3, 4]],
  output_label: null,
  photo_slot: { width: 555, height: 740 },
}
const PLAN_STRIP = {
  ...PLAN_46,
  frame_id: 'fs',
  template_key: 'strip_2x6',
  layout_label: '2×6',
  captures: 6,
  outputs: 2,
  photos_per_output: 3,
  output_capture_groups: [
    [1, 2, 3],
    [4, 5, 6],
  ],
  output_label: '2 strips',
  photo_slot: { width: 540, height: 405 },
}

function menu(frames: FrameMenu['frames'], surprise = false): FrameMenu {
  return {
    frames,
    layouts: [...new Set(frames.map((f) => f.plan.template_key))],
    allow_surprise_me: surprise,
    theme: { background: '#101418', heading: '#FFFFFF', primary_bg: '#2255CC', primary_text: '#FFFFFF' },
    start_screen: { start_button_text: 'Start', logo_url: null, background_url: null },
    countdown_seconds: 5,
  }
}

const MENU = menu([
  { id: 'f46', name: 'Gold', preview_url: '/api/booth/frames/f46/preview.jpg?v=1', plan: PLAN_46 },
  { id: 'fs', name: 'Night', preview_url: '/api/booth/frames/fs/preview.jpg?v=1', plan: PLAN_STRIP },
])

const VISIT = {
  id: '11111111-1111-4111-8111-111111111111',
  state: 'eligibility_ok',
  state_version: 1,
  countdown_seconds: 5,
  mirror: true,
  retake_mode: 'per_photo',
  expected_captures: 0,
  taken: 0,
  template_key: null,
  layout_label: null,
  frame_id: null,
  shots: [],
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage(fetcher: (path: string, init?: RequestInit) => Promise<Response>) {
  const keys = { get: () => 'k'.repeat(43), set: () => undefined, clear: () => undefined }
  const client = createApiClient(fetcher, keys)
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ApiClientProvider client={client}>
        <MemoryRouter initialEntries={['/booth/frames']}>
          <Routes>
            <Route path="/booth/frames" element={<FrameSelectPage />} />
            <Route path="/booth/capture" element={<p>the camera screen</p>} />
          </Routes>
        </MemoryRouter>
      </ApiClientProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => sessionStorage.clear())

/** The frame the carousel has settled on: the only one that can be chosen. */
function currentSlide(): HTMLElement {
  const slides = screen.getAllByTestId('frame-slide').filter((s) => s.hasAttribute('data-current'))
  expect(slides).toHaveLength(1)
  return slides[0] as HTMLElement
}

async function useCurrentFrame() {
  await userEvent.click(within(currentSlide()).getByRole('button', { name: 'Use this frame' }))
}

/** The centred question that "Use this frame" opens; only its main answer starts the visit. */
function question(): HTMLElement {
  return screen.getByRole('dialog', { name: 'Use this frame?' })
}

async function startWithFrame() {
  await userEvent.click(within(question()).getByRole('button', { name: 'Start with this frame' }))
}

async function nextFrame() {
  await userEvent.click(screen.getByRole('button', { name: 'Next frame' }))
}

describe('FrameSelectPage (booth)', () => {
  it('confirming a frame starts the visit with that frame and opens the camera screen', async () => {
    const posted: { path: string; body: unknown }[] = []
    const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/booth/frames') return json(MENU)
      posted.push({ path, body: JSON.parse(String(init?.body)) })
      if (path === '/api/booth/sessions') return json(VISIT, 201)
      if (path.endsWith('/frame')) {
        return json({ ...VISIT, state: 'capturing', expected_captures: 6, frame_id: 'fs' })
      }
      return json({ detail: 'nope' }, 404)
    })
    renderPage(fetcher)
    const screenEl = await screen.findByRole('group', { name: 'Frame selection' })
    expect(screenEl.style.getPropertyValue('--ev-primary-bg')).toBe('#2255CC')
    expect(screen.queryByRole('list', { name: 'Frames' })).toBeNull() // still the carousel

    await nextFrame()
    await useCurrentFrame()
    expect(posted).toEqual([]) // asking keeps nothing and starts nothing

    await startWithFrame()
    expect(await screen.findByText('the camera screen')).toBeInTheDocument()
    expect(posted.map((call) => call.path)).toEqual([
      '/api/booth/sessions',
      `/api/booth/sessions/${VISIT.id}/frame`,
    ])
    expect(posted[1]?.body).toEqual({ frame_id: 'fs' })
    expect(sessionStorage.getItem(SESSION_FRAME_KEY)).toBe('fs')
  })

  it('explains when no event is active', async () => {
    renderPage(async () => json({ detail: 'no event is active on this booth yet' }, 404))
    expect(await screen.findByRole('alert')).toHaveTextContent('This booth has no active event yet.')
  })

  it('a frame the event no longer offers asks the participant to pick again', async () => {
    renderPage(async (path) => {
      if (path === '/api/booth/frames') return json(MENU)
      if (path === '/api/booth/sessions') return json(VISIT, 201)
      return json({ detail: 'frame is not offered' }, 404)
    })
    await screen.findByTestId('frame-carousel')
    await useCurrentFrame()
    await startWithFrame()
    expect(await screen.findByText('That frame could not be chosen. Please pick again.')).toBeInTheDocument()
    expect(screen.queryByText('the camera screen')).toBeNull()
    expect(sessionStorage.getItem(SESSION_FRAME_KEY)).toBeNull()
  })

  it('a retry after a lost answer joins the same visit instead of starting a second one', async () => {
    const keys: string[] = []
    let attempt = 0
    renderPage(async (path, init) => {
      if (path === '/api/booth/frames') return json(MENU)
      if (path === '/api/booth/sessions') {
        keys.push((JSON.parse(String(init?.body)) as { idempotency_key: string }).idempotency_key)
        return json(VISIT, 201)
      }
      attempt += 1
      if (attempt === 1) return json({ detail: 'lost' }, 503)
      return json({ ...VISIT, state: 'capturing', expected_captures: 2, frame_id: 'f46' })
    })
    await screen.findByTestId('frame-carousel')
    await useCurrentFrame()
    await startWithFrame()
    expect(await screen.findByText('That frame could not be chosen. Please pick again.')).toBeInTheDocument()
    await useCurrentFrame()
    await startWithFrame()
    expect(await screen.findByText('the camera screen')).toBeInTheDocument()
    expect(keys).toHaveLength(2)
    expect(new Set(keys).size).toBe(2) // a fresh key only after the failure, never mid-flight
  })

  it('an answer arriving after the screen was left is ignored (P5R2-002)', async () => {
    let release: (() => void) | null = null
    const { unmount } = renderPage(async (path) => {
      if (path === '/api/booth/frames') return json(MENU)
      if (path === '/api/booth/sessions') return json(VISIT, 201)
      await new Promise<void>((resolve) => {
        release = resolve
      })
      return json({ ...VISIT, state: 'capturing' })
    })
    await screen.findByTestId('frame-carousel')
    await useCurrentFrame()
    await startWithFrame()
    unmount()
    await act(async () => {
      release?.()
      await Promise.resolve()
    })
    expect(sessionStorage.getItem(SESSION_FRAME_KEY)).toBeNull()
  })

  it('coming back to the screen opens the carousel on the frame chosen before', async () => {
    sessionStorage.setItem(SESSION_FRAME_KEY, 'fs')
    renderPage(async (path) => (path === '/api/booth/frames' ? json(MENU) : json(VISIT, 201)))
    await screen.findByTestId('frame-carousel')
    expect(currentSlide()).toHaveAttribute('aria-label', 'Night, 2 of 2')
  })
})
