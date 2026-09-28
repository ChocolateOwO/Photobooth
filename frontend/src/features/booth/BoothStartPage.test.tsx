import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'

import { ApiClientProvider } from '../../shared/api/ApiClientContext'
import { createApiClient, type FrameMenu } from '../../shared/api/client'
import { tokenVar } from '../../shared/eventTheme/theme'
import { BoothStartPage } from './BoothStartPage'
import { FrameSelectPage } from './FrameSelectPage'

const THEME = { background: '#101418', heading: '#F0E6D2', primary_bg: '#AA2244', primary_text: '#FFFFFF' }

const PLAN = {
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

function menu(start: FrameMenu['start_screen']): FrameMenu {
  return {
    frames: [{ id: 'f46', name: 'Gold', preview_url: '/api/booth/frames/f46/preview.jpg?v=1', plan: PLAN }],
    layouts: ['print_4x6'],
    allow_surprise_me: false,
    theme: THEME,
    start_screen: start,
    countdown_seconds: 5,
  }
}

const FULL = menu({
  start_button_text: "Let's go",
  logo_url: '/api/booth/start/logo?v=abc',
  background_url: '/api/booth/start/background?v=def',
})

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderBooth(answer: () => Response) {
  const keys = { get: () => 'k'.repeat(43), set: () => undefined, clear: () => undefined }
  const client = createApiClient(async () => answer(), keys)
  const router = createMemoryRouter(
    [
      { path: '/booth', element: <BoothStartPage /> },
      { path: '/booth/frames', element: <FrameSelectPage /> },
    ],
    { initialEntries: ['/booth'] },
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ApiClientProvider client={client}>
        <RouterProvider router={router} />
      </ApiClientProvider>
    </QueryClientProvider>,
  )
  return router
}

describe('BoothStartPage (the real participant start screen)', () => {
  it('shows the background, the logo, the theme and the Start text, and nothing else', async () => {
    renderBooth(() => json(FULL))
    const screenEl = await screen.findByRole('group', { name: 'Start screen' })
    expect(screenEl.style.backgroundImage).toContain('/api/booth/start/background?v=def')
    expect(screenEl.style.getPropertyValue(tokenVar('primary_bg'))).toBe('#AA2244')
    expect(within(screenEl).getAllByRole('img')).toHaveLength(1)
    expect(within(screenEl).getByRole('img', { name: 'Event logo' })).toHaveAttribute(
      'src',
      '/api/booth/start/logo?v=abc',
    )
    expect(within(screenEl).getAllByRole('button').map((b) => b.textContent)).toEqual(["Let's go"])
    // Drawn by the shared StartScreen component (the one the admin preview uses).
    expect(within(screenEl).getByTestId('start-screen')).toBeInTheDocument()
    expect(within(screenEl).queryByRole('textbox')).toBeNull()
    for (const gone of [/email/i, /back/i, /print/i, /frames? to choose/i, /photos are ready/i, /layout/i]) {
      expect(within(screenEl).queryByText(gone)).toBeNull()
    }
  })

  it('uses the neutral Photobooth mark without a logo and when the logo can not load', async () => {
    renderBooth(() => json(menu({ start_button_text: 'Start', logo_url: null, background_url: null })))
    const screenEl = await screen.findByRole('group', { name: 'Start screen' })
    expect(within(screenEl).getByRole('img', { name: 'Photobooth' })).toBeInTheDocument()
    expect(screenEl.style.backgroundImage).toBe('')
  })

  it('falls back to the mark when the logo file is gone', async () => {
    renderBooth(() => json(FULL))
    const logo = await screen.findByRole('img', { name: 'Event logo' })
    fireEvent.error(logo)
    expect(screen.queryByRole('img', { name: 'Event logo' })).toBeNull()
    expect(screen.getByRole('img', { name: 'Photobooth' })).toBeInTheDocument()
  })

  it('Start opens the frame selection screen', async () => {
    const router = renderBooth(() => json(FULL))
    await userEvent.click(await screen.findByRole('button', { name: "Let's go" }))
    expect(router.state.location.pathname).toBe('/booth/frames')
    expect(await screen.findByRole('heading', { name: 'Choose your frame' })).toBeInTheDocument()
  })

  it('takes the whole display, exactly as the organizer test does', async () => {
    renderBooth(() => json(FULL))
    // The same shell the Admin "Test booth" runs; a guest's booth has no app frame around it.
    expect(await screen.findByTestId('booth-shell')).toBeInTheDocument()
    expect(document.documentElement).toHaveAttribute('data-booth-immersive')
  })

  it('explains when no event is active', async () => {
    renderBooth(() => json({ detail: 'no event is active on this booth yet' }, 404))
    expect(await screen.findByRole('alert')).toHaveTextContent('This booth has no active event yet.')
  })
})
