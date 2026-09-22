import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

function signedInServer() {
  const server = new FakeAdminServer()
  server.signedIn = true
  return server
}

function shownList() {
  return screen.getByRole('list', { name: 'Frames shown to participants' })
}

function shownNames(): string[] {
  return within(shownList())
    .getAllByTestId('available-frame-row')
    .map((row) => row.querySelector('span:nth-of-type(2)')?.textContent ?? '')
}

async function fillRequired() {
  await userEvent.type(await screen.findByLabelText('Profile name'), 'Expo')
  await userEvent.type(screen.getByLabelText('Title'), 'Welcome')
}

describe('Available frames for participants', () => {
  it('a new profile offers every built-in frame, never an upload by itself', async () => {
    const server = signedInServer()
    const mine = server.seedFrame('strip_2x6', 'Our strip')
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    expect(screen.getByTestId('available-frames-summary')).toHaveTextContent(
      '6 frames available to participants',
    )
    const off = screen.getByRole('switch', { name: 'Show Our strip (2×6) to participants' })
    expect(off).not.toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    const saved = [...server.profiles.values()][0]?.settings
    expect(saved?.available_frames).toEqual(server.builtinIds())
    expect(saved?.available_frames).not.toContain(mine.id)
  })

  it('rows are compact: thumbnail, name, layout, switch and reorder only', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    const row = (await screen.findAllByTestId('available-frame-row'))[0] as HTMLElement
    expect(within(row).getByRole('switch')).toBeChecked()
    expect(within(row).getByText('2×6')).toBeInTheDocument()
    expect(row.querySelector('img')).not.toBeNull()
    expect(within(row).getByRole('button', { name: /Move .* down/ })).toBeInTheDocument()
    const section = screen.getByRole('region', { name: 'Available frames for participants' })
    for (const word of ['Replace', 'Rename', 'Delete', ' px', 'Download']) {
      expect(section.textContent).not.toContain(word)
    }
    expect(within(section).getByRole('link', { name: 'Manage all frames' })).toHaveAttribute(
      'href',
      '/admin/frames',
    )
  })

  it('switches frames on and off, reorders them and saves the exact list', async () => {
    const server = signedInServer()
    const a = server.seedFrame('strip_2x6', 'Strip A')
    const b = server.seedFrame('strip_2x6', 'Strip B')
    const profile = server.seedProfile({ name: 'Expo', available_frames: [] })
    renderAdmin(`/admin/profiles/${profile.id}`, { server })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No frames are available to participants.',
    )
    // Two frames of the same layout can both be offered.
    await userEvent.click(screen.getByRole('switch', { name: 'Show Strip A (2×6) to participants' }))
    await userEvent.click(screen.getByRole('switch', { name: 'Show Strip B (2×6) to participants' }))
    await userEvent.click(screen.getByRole('switch', { name: 'Show Midnight (2×6) to participants' }))
    expect(shownNames()).toEqual(['Strip A', 'Strip B', 'Midnight'])
    await userEvent.click(screen.getByRole('button', { name: 'Move Strip B up' }))
    expect(shownNames()).toEqual(['Strip B', 'Strip A', 'Midnight'])
    await userEvent.click(screen.getByRole('button', { name: 'Move Strip B down' }))
    expect(shownNames()).toEqual(['Strip A', 'Strip B', 'Midnight'])
    expect(screen.getByTestId('available-frames-summary')).toHaveTextContent('3 frames available')

    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.get(profile.id)?.revision).toBe(2))
    expect(server.profiles.get(profile.id)?.settings.available_frames).toEqual([
      a.id,
      b.id,
      server.builtin('midnight', 'strip_2x6').id,
    ])
  })

  it('enables or disables a whole layout, and the last frame of a layout removes it', async () => {
    const server = signedInServer()
    const profile = server.seedProfile({ name: 'Expo' })
    renderAdmin(`/admin/profiles/${profile.id}`, { server })
    await screen.findAllByTestId('available-frame-row')
    const caption = () => screen.getByTestId('preparation-preview').textContent ?? ''
    expect(caption()).toContain('Layouts offered: 2x6 photo strip, 4x6 print')
    await userEvent.click(screen.getByRole('button', { name: /Disable all 2×6/ }))
    expect(shownNames()).toHaveLength(3)
    expect(caption()).not.toContain('2x6 photo strip')
    await userEvent.click(screen.getByRole('button', { name: /Enable all 2×6/ }))
    expect(shownNames()).toHaveLength(6)
    expect(caption()).toContain('2x6 photo strip')
  })

  it('searches by name and filters by layout', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Gold rush')
    renderAdmin('/admin/profiles/new', { server })
    await screen.findAllByTestId('available-frame-row')
    await userEvent.type(screen.getByLabelText('Search frames'), 'gold')
    const rows = screen.getAllByTestId('available-frame-row')
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('Celebration Gold'),
      expect.stringContaining('Celebration Gold'),
      expect.stringContaining('Gold rush'),
    ])
    await userEvent.clear(screen.getByLabelText('Search frames'))
    await userEvent.click(screen.getByRole('button', { name: '2×6', pressed: false }))
    expect(screen.getAllByTestId('available-frame-row').every((r) => r.textContent?.includes('2×6'))).toBe(true)
  })

  it('saves the Surprise me option', async () => {
    const server = signedInServer()
    const profile = server.seedProfile({ name: 'Expo' })
    renderAdmin(`/admin/profiles/${profile.id}`, { server })
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Allow “Surprise me” random frame' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.get(profile.id)?.settings.allow_surprise_me).toBe(true))
  })

  it('keeps the saved list locked with a retry while the frames can not be loaded (P5-005)', async () => {
    const server = signedInServer()
    const profile = server.seedProfile({ name: 'Expo' })
    server.frameListFailures = 1
    renderAdmin(`/admin/profiles/${profile.id}`, { server })
    const alert = (await screen.findByText(/The frames could not be loaded/)).closest('[role="alert"]') as HTMLElement
    await userEvent.type(screen.getByLabelText('Title'), '!')
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.get(profile.id)?.revision).toBe(2))
    expect(server.profiles.get(profile.id)?.settings.available_frames).toEqual(server.builtinIds())
    await userEvent.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await screen.findAllByRole('switch')).not.toHaveLength(0)
  })
})

describe('A new profile while the frames can not be loaded (P5R2-001)', () => {
  it('saves with every built-in frame instead of an empty list', async () => {
    const server = signedInServer()
    server.frameListFailures = 100
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    expect(await screen.findByText(/Saving offers every built-in frame/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    expect([...server.profiles.values()][0]?.settings.available_frames).toEqual(server.builtinIds())
  })
})
describe('Preview: frame selection mode', () => {
  it('shows the participant gallery with the enabled frames in their order', async () => {
    const server = signedInServer()
    const a = server.seedFrame('strip_2x6', 'Strip A')
    const profile = server.seedProfile({
      name: 'Expo',
      available_frames: [a.id, server.builtin('celebration_gold', 'print_4x6').id],
    })
    renderAdmin(`/admin/profiles/${profile.id}`, { server })
    await screen.findAllByTestId('available-frame-row')
    await userEvent.click(screen.getByRole('button', { name: 'Frame selection' }))
    const preview = screen.getByTestId('event-preview')
    const gallery = within(preview).getByTestId('frame-gallery')
    const cards = within(within(gallery).getByRole('list', { name: 'Frames' })).getAllByRole('button')
    expect(cards.map((c) => c.getAttribute('aria-label'))).toEqual([
      'Strip A, 2×6 • 6 photos • 2 strips',
      expect.stringContaining('Celebration Gold'),
    ])
    expect(gallery.textContent).not.toContain('Built-in')
    await userEvent.click(cards[0] as HTMLElement)
    expect(within(preview).getByRole('dialog', { name: 'Strip A' })).toBeInTheDocument()
    expect(within(screen.getByTestId('event-preview-phone')).getByTestId('frame-gallery')).toBeInTheDocument()
  })
})
