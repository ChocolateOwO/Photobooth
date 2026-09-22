import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

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
}

function menu(frames: FrameMenu['frames'], surprise = false): FrameMenu {
  return {
    frames,
    layouts: [...new Set(frames.map((f) => f.plan.template_key))],
    allow_surprise_me: surprise,
    theme: { background: '#101418', heading: '#FFFFFF', primary_bg: '#2255CC', primary_text: '#FFFFFF' },
  }
}

const MENU = menu([
  { id: 'f46', name: 'Gold', preview_url: '/api/booth/frames/f46/preview.jpg?v=1', plan: PLAN_46 },
  { id: 'fs', name: 'Night', preview_url: '/api/booth/frames/fs/preview.jpg?v=1', plan: PLAN_STRIP },
])

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage(fetcher: (path: string, init?: RequestInit) => Promise<Response>) {
  const keys = { get: () => 'k'.repeat(43), set: () => undefined, clear: () => undefined }
  const client = createApiClient(fetcher, keys)
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ApiClientProvider client={client}>
        <FrameSelectPage />
      </ApiClientProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => sessionStorage.clear())

describe('FrameSelectPage (booth)', () => {
  it('shows the event frames in its theme, confirms a choice and keeps the plan', async () => {
    const posted: unknown[] = []
    const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/booth/frames') return json(MENU)
      if (path === '/api/booth/frame-choice') {
        posted.push(JSON.parse(String(init?.body)))
        return json(PLAN_STRIP)
      }
      return json({ detail: 'nope' }, 404)
    })
    renderPage(fetcher)
    const screenEl = await screen.findByRole('group', { name: 'Frame selection' })
    expect(screenEl.style.getPropertyValue('--ev-primary-bg')).toBe('#2255CC')
    const list = screen.getByRole('list', { name: 'Frames' })
    expect(within(list).getAllByRole('button').map((b) => b.textContent)).toEqual([
      expect.stringContaining('Gold'),
      expect.stringContaining('Night'),
    ])

    await userEvent.click(within(list).getByRole('button', { name: /Night/ }))
    expect(posted).toEqual([]) // tapping only previews
    await userEvent.click(screen.getByRole('button', { name: 'Use this frame' }))
    expect(posted).toEqual([{ frame_id: 'fs' }])
    expect(JSON.parse(sessionStorage.getItem(SESSION_FRAME_KEY) ?? '{}')).toMatchObject({
      frame_id: 'fs',
      captures: 6,
      outputs: 2,
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Start with this frame' }))
    expect(screen.getByText(/Ready: Night \(2×6 • 6 photos • 2 strips\)/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Choose a different frame' }))
    expect(sessionStorage.getItem(SESSION_FRAME_KEY)).toBeNull()
    expect(screen.getByRole('heading', { name: 'Choose your frame' })).toBeInTheDocument()
  })

  it('explains when no event is active', async () => {
    renderPage(async () => json({ detail: 'no event is active on this booth yet' }, 404))
    expect(await screen.findByRole('alert')).toHaveTextContent('This booth has no active event yet.')
  })

  it('a refused choice asks the participant to pick again', async () => {
    renderPage(async (path) =>
      path === '/api/booth/frames' ? json(MENU) : json({ detail: 'not offered' }, 404),
    )
    await userEvent.click(await screen.findByRole('button', { name: /Gold/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Use this frame' }))
    expect(await screen.findByText('That frame could not be chosen. Please pick again.')).toBeInTheDocument()
    expect(sessionStorage.getItem(SESSION_FRAME_KEY)).toBeNull()
  })
})
