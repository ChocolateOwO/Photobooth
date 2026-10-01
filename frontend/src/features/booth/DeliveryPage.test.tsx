import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'

import { ApiClientProvider } from '../../shared/api/ApiClientContext'
import {
  createApiClient,
  type BoothSessionState,
  type DeliveryLink,
  type FrameMenu,
} from '../../shared/api/client'
import { DeliveryPage } from './DeliveryPage'

/**
 * The end of a visit: the booth asks for the finished photos exactly once (retrying the same
 * request while the render worker is busy), shows them beside the take-home QR code, and goes
 * back to its start when the guest is done or walks away.
 */

const SESSION_ID = '33333333-3333-4333-8333-333333333333'
const URL = 'http://192.168.1.20:8113/d/' + 'T'.repeat(43)

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

const DELIVERED_OUTPUTS: NonNullable<BoothSessionState['outputs']> = [
  { id: 'out-1', output_index: 1, width: 600, height: 1800, version: 'v1' },
  { id: 'out-2', output_index: 2, width: 600, height: 1800, version: 'v2' },
]

const LINK: DeliveryLink = {
  url: URL,
  expires_at: '2026-10-07T07:00:00Z',
  qr_svg: '<svg xmlns="http://www.w3.org/2000/svg" class="qr"><title>QR code</title></svg>',
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
  renders: string[]
  links: number
  gaveUp: number
  current: BoothSessionState
}

function server(start: BoothSessionState, busyFirst = 0, failRender = false): {
  booth: Booth
  fetcher: (path: string, init?: RequestInit) => Promise<Response>
} {
  const booth: Booth = { renders: [], links: 0, gaveUp: 0, current: start }
  let busy = busyFirst
  const fetcher = async (path: string, init?: RequestInit): Promise<Response> => {
    if (path === '/api/booth/frames') return json(MENU)
    if (path === '/api/booth/sessions/current') return json(booth.current)
    if (path.endsWith('/render')) {
      const body = JSON.parse(String(init?.body)) as { idempotency_key: string }
      booth.renders.push(body.idempotency_key)
      if (busy > 0) {
        busy -= 1
        return json({ detail: 'busy' }, 503)
      }
      if (failRender) return json({ detail: 'the photos could not be made' }, 409)
      booth.current = { ...booth.current, state: 'delivered', outputs: DELIVERED_OUTPUTS }
      return json(booth.current)
    }
    if (path.endsWith('/delivery')) {
      booth.links += 1
      return json(LINK)
    }
    if (path.endsWith('/give-up')) {
      booth.gaveUp += 1
      booth.current = { ...booth.current, state: 'completed' }
      return json(booth.current)
    }
    return json({ detail: `unexpected ${path}` }, 500)
  }
  return { booth, fetcher }
}

function renderDone(fetcher: (path: string, init?: RequestInit) => Promise<Response>): void {
  const keys = { get: () => 'k'.repeat(43), set: () => undefined, clear: () => undefined }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ApiClientProvider client={createApiClient(fetcher, keys)}>
        <MemoryRouter initialEntries={['/booth/done']}>
          <Routes>
            <Route path="/booth/done" element={<DeliveryPage />} />
            <Route path="/booth/capture" element={<p>the camera screen</p>} />
            <Route path="/booth" element={<p>the start screen</p>} />
          </Routes>
        </MemoryRouter>
      </ApiClientProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('DeliveryPage (the finished photos)', () => {
  it('asks for the finished photos once and shows them beside the take-home QR code', async () => {
    const { booth, fetcher } = server(visit())
    renderDone(fetcher)
    expect(screen.getByTestId('booth-shell')).toBeInTheDocument()

    const photos = await screen.findByTestId('finished-photos')
    expect(within(photos).getAllByRole('img').map((img) => img.getAttribute('src'))).toEqual([
      `/api/booth/sessions/${SESSION_ID}/outputs/out-1.jpg?v=v1`,
      `/api/booth/sessions/${SESSION_ID}/outputs/out-2.jpg?v=v2`,
    ])
    expect(booth.renders).toHaveLength(1)
    expect(booth.links).toBe(1)

    const qr = screen.getByTestId('delivery-qr')
    expect(qr.getAttribute('src')).toBe(
      `data:image/svg+xml;charset=utf-8,${encodeURIComponent(LINK.qr_svg)}`,
    )
    expect(screen.getByTestId('delivery-url')).toHaveTextContent(URL)
    expect(screen.getByText(/same Wi-Fi as the booth/)).toBeInTheDocument()
    expect(screen.getByText(/The link works until/)).toBeInTheDocument()
  })

  it('asks a busy render worker again with the very same request', async () => {
    const { booth, fetcher } = server(visit(), 2)
    renderDone(fetcher)
    expect(await screen.findByTestId('making-photos')).toHaveTextContent('Making your photos')
    await act(async () => {
      vi.advanceTimersByTime(1600)
    })
    await act(async () => {
      vi.advanceTimersByTime(1600)
    })
    await screen.findByTestId('finished-photos')
    expect(booth.renders).toHaveLength(3)
    expect(new Set(booth.renders).size).toBe(1) // one key: the photos can only be made once
  })

  it('a reload of a delivered visit shows it again without making anything', async () => {
    const { booth, fetcher } = server(visit({ state: 'delivered', outputs: DELIVERED_OUTPUTS }))
    renderDone(fetcher)
    await screen.findByTestId('finished-photos')
    expect(booth.renders).toEqual([])
    expect(booth.links).toBe(1)
  })

  it('says so when the photos can not be made, and starts over', async () => {
    const { booth, fetcher } = server(visit(), 0, true)
    renderDone(fetcher)
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be made')
    await userEvent.click(screen.getByRole('button', { name: 'Start over' }))
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
    expect(booth.gaveUp).toBe(1) // the visit it knew about is closed, not left behind
  })

  it('leaves a failure screen by itself when nobody is there (P8-006)', async () => {
    const { booth, fetcher } = server(visit({ inactivity_timeout_s: 30 }), 0, true)
    renderDone(fetcher)
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be made')
    await act(async () => {
      vi.advanceTimersByTime(31_000)
    })
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
    await waitFor(() => expect(booth.gaveUp).toBe(1))
  })

  it('Done ends the visit and the booth is ready for the next guest', async () => {
    const { booth, fetcher } = server(visit())
    renderDone(fetcher)
    await screen.findByTestId('finished-photos')
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
    expect(booth.gaveUp).toBe(1)
  })

  it('goes back to the start by itself when nobody is there any more', async () => {
    const { booth, fetcher } = server(visit({ inactivity_timeout_s: 30 }))
    renderDone(fetcher)
    await screen.findByTestId('finished-photos')
    await act(async () => {
      vi.advanceTimersByTime(31_000)
    })
    expect(await screen.findByText('the start screen')).toBeInTheDocument()
    await waitFor(() => expect(booth.gaveUp).toBe(1))
  })

  it('sends a visit that is still taking photos back to the camera', async () => {
    const { booth, fetcher } = server(visit({ state: 'capturing', taken: 3 }))
    renderDone(fetcher)
    expect(await screen.findByText('the camera screen')).toBeInTheDocument()
    expect(booth.renders).toEqual([])
  })

  it('wears the event theme', async () => {
    const { fetcher } = server(visit())
    renderDone(fetcher)
    await screen.findByTestId('finished-photos')
    const themed = screen.getByRole('group', { name: 'Your photos' })
    expect(themed.style.getPropertyValue('--ev-primary-bg')).toBe('#AA3311')
  })
})
