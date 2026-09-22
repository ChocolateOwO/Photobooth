import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { tokenVar } from '../../../shared/eventTheme/theme'
import { FakeAdminServer, presetById } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

function signedInServer() {
  const server = new FakeAdminServer()
  server.signedIn = true
  return server
}

async function fillRequired() {
  await userEvent.type(await screen.findByLabelText('Profile name'), 'Expo')
  await userEvent.type(screen.getByLabelText('Title'), 'Welcome')
}

function sizes() {
  return screen.getByRole('group', { name: 'Photo sizes available' })
}

function previewVar(key: string): string {
  const screenEl = within(screen.getByTestId('event-preview')).getByRole('group', {
    name: 'Start screen preview',
  })
  return screenEl.style.getPropertyValue(tokenVar(key))
}

describe('Photo sizes available (the profile chooses sizes, never single frames)', () => {
  it('shows only the size pills with their frame counts, and no per-frame controls', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Our strip')
    renderAdmin('/admin/profiles/new', { server })
    await screen.findByTestId('available-frames-summary') // counts come with the frame list
    const pills = within(sizes()).getAllByRole('button')
    expect(pills.map((p) => p.textContent)).toEqual(['2×6 · 4 frames', '4×6 · 3 frames'])
    expect(pills.every((p) => p.getAttribute('aria-pressed') === 'true')).toBe(true) // all sizes
    expect(screen.getByTestId('available-frames-summary')).toHaveTextContent('7 frames available to participants.')
    // Nothing about single frames: no search, rows, switches, handles or ordering.
    expect(screen.queryByLabelText('Search frames')).toBeNull()
    expect(screen.queryAllByTestId('available-frame-row')).toHaveLength(0)
    expect(screen.queryByRole('switch', { name: /to participants/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Move / })).toBeNull()
    expect(screen.queryByRole('button', { name: /^(Enable|Disable) all/ })).toBeNull()
    expect(screen.getByRole('link', { name: 'Manage all frames' })).toHaveAttribute('href', '/admin/frames')
  })

  it('saves the chosen sizes; with none chosen it says so', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    const strip = within(sizes()).getByRole('button', { name: /^2×6/ })
    await userEvent.click(strip)
    expect(strip).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByTestId('available-frames-summary')).toHaveTextContent('3 frames')
    await userEvent.click(within(sizes()).getByRole('button', { name: /^4×6/ }))
    expect(screen.getByRole('alert')).toHaveTextContent('No photo size is chosen.')
    await userEvent.click(within(sizes()).getByRole('button', { name: /^4×6/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    expect([...server.profiles.values()][0]?.settings.enabled_layouts).toEqual(['print_4x6'])
  })

  it('a new profile offers every size even when the frame list can not be loaded', async () => {
    const server = signedInServer()
    server.frameListFailures = 100
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    // No counts without the list, but the sizes are there and chosen.
    const pills = within(sizes()).getAllByRole('button')
    expect(pills.map((p) => p.textContent)).toEqual(['2×6', '4×6'])
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    expect([...server.profiles.values()][0]?.settings.enabled_layouts).toEqual(['strip_2x6', 'print_4x6'])
  })

  it('the preview gallery shows every valid frame of the chosen sizes, uploads included', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Alpha strip')
    server.seedFrame('strip_2x6', 'Broken', [], { status: 'invalid' })
    const profile = server.seedProfile({ name: 'Expo', enabled_layouts: ['strip_2x6'] })
    renderAdmin(`/admin/profiles/${profile.id}`, { server })
    await screen.findByLabelText('Profile name')
    await userEvent.click(screen.getByRole('button', { name: 'Frame selection' }))
    const gallery = within(screen.getByTestId('event-preview')).getByTestId('frame-gallery')
    const cards = within(within(gallery).getByRole('list', { name: 'Frames' })).getAllByRole('button')
    expect(cards.map((c) => c.getAttribute('aria-label')?.split(',')[0])).toEqual([
      'Celebration Gold',
      'Midnight',
      'Minimal Light',
      'Alpha strip',
    ])
    expect(gallery.textContent).not.toContain('Built-in')
  })

  it('moves "Surprise me" to the booth settings as a switch and saves it', async () => {
    const server = signedInServer()
    const profile = server.seedProfile({ name: 'Expo' })
    renderAdmin(`/admin/profiles/${profile.id}`, { server })
    const surprise = await screen.findByRole('switch', { name: 'Allow “Surprise me” random frame' })
    await userEvent.click(surprise)
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.get(profile.id)?.settings.allow_surprise_me).toBe(true))
  })
})

describe('Countdown (1-10 seconds)', () => {
  it('starts at 5 and moves with the arrow buttons, stopping at 1 and 10', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    const field = screen.getByRole('spinbutton', { name: 'Countdown before each photo' })
    expect(field).toHaveValue('5')
    expect(field).toHaveAttribute('aria-valuetext', '5 seconds')
    const up = screen.getByRole('button', { name: 'Increase countdown' })
    const down = screen.getByRole('button', { name: 'Decrease countdown' })
    for (let i = 0; i < 7; i++) await userEvent.click(up)
    expect(field).toHaveValue('10')
    expect(up).toBeDisabled()
    for (let i = 0; i < 12; i++) if (!down.hasAttribute('disabled')) await userEvent.click(down)
    expect(field).toHaveValue('1')
    expect(down).toBeDisabled()
    await userEvent.click(up)
    await userEvent.click(up)
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    expect([...server.profiles.values()][0]?.settings.countdown_seconds).toBe(3)
  })

  it('works with the keyboard arrow keys', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    const field = await screen.findByRole('spinbutton', { name: 'Countdown before each photo' })
    field.focus()
    await userEvent.keyboard('{ArrowUp}{ArrowUp}')
    expect(field).toHaveValue('7')
    await userEvent.keyboard('{ArrowDown}')
    expect(field).toHaveValue('6')
  })

  it('reports an empty, out-of-range or non-whole value in the problems pop-up', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    const field = screen.getByRole('spinbutton', { name: 'Countdown before each photo' })
    for (const bad of ['', '0', '11', '2.5']) {
      await userEvent.clear(field)
      if (bad) await userEvent.type(field, bad)
      await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
      const dialog = await screen.findByRole('alertdialog', { name: 'Some information is missing or invalid' })
      expect(dialog).toHaveTextContent('Countdown must be a whole number from 1 to 10 seconds.')
      await userEvent.keyboard('{Escape}')
      await waitFor(() => expect(field).toHaveFocus())
      expect(field).toHaveAttribute('aria-invalid', 'true')
    }
    expect(server.profiles.size).toBe(0)
    await userEvent.clear(field)
    await userEvent.type(field, '9')
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    expect([...server.profiles.values()][0]?.settings.countdown_seconds).toBe(9)
  })
})

describe('Main colours (Button and Text only)', () => {
  it('shows two round colour pickers and a reset, never the 35-colour editor', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    await screen.findByLabelText('Profile name')
    const group = screen.getByRole('group', { name: 'Main colours' })
    const pickers = within(group).getAllByLabelText(/colour$/)
    expect(pickers.map((p) => p.getAttribute('aria-label'))).toEqual(['Button colour', 'Text colour'])
    const midnight = presetById('midnight_blue').tokens
    expect(within(group).getByLabelText('Button colour')).toHaveValue((midnight.primary_bg ?? '').toLowerCase())
    expect(within(group).getByLabelText('Text colour')).toHaveValue((midnight.heading ?? '').toLowerCase())
    expect(within(group).getByRole('button', { name: 'Reset to recommended colours' })).toBeInTheDocument()
    expect(screen.queryByText('Advanced colors')).toBeNull()
    expect(screen.queryByLabelText('Headings hex value')).toBeNull()
    expect(screen.queryAllByRole('textbox', { name: /hex value$/ })).toHaveLength(0)
  })

  it('a new Button colour regenerates the related colours and marks the theme custom', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    const button = screen.getByLabelText('Button colour')
    await act(async () => {
      button.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await userEvent.click(button)
    // Colour inputs report changes through input events.
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(button, '#aa2244')
      button.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await waitFor(() => expect(server.mainColourRequests.at(-1)).toEqual({ button: '#AA2244', text: presetById('midnight_blue').tokens.heading }))
    await waitFor(() => expect(previewVar('primary_bg')).toBe('#AA2244'))
    expect(previewVar('primary_hover')).toBe('#AA2244') // regenerated by the server
    expect(screen.getByRole('radio', { name: /^Midnight Blue/ })).not.toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    const theme = [...server.profiles.values()][0]?.settings.theme
    expect(theme?.tokens.primary_bg).toBe('#AA2244')
    expect(theme?.source).toBe('custom')
    expect(theme?.preset).toBe('midnight_blue')
  })

  it('a quick theme sets both main colours; reset returns to the recommended colours', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    await userEvent.click(screen.getByRole('radio', { name: /^Forest Fresh/ }))
    const forest = presetById('forest_fresh').tokens
    expect(screen.getByLabelText('Button colour')).toHaveValue((forest.primary_bg ?? '').toLowerCase())
    expect(screen.getByLabelText('Text colour')).toHaveValue((forest.heading ?? '').toLowerCase())
    const text = screen.getByLabelText('Text colour')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(text, '#123456')
      text.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await waitFor(() => expect(previewVar('heading')).toBe('#123456'))
    await userEvent.click(screen.getByRole('button', { name: 'Reset to recommended colours' }))
    expect(previewVar('heading')).toBe(forest.heading)
    expect(screen.getByRole('radio', { name: /^Forest Fresh/ })).toBeChecked()
  })

  it('a late colour answer never overwrites a quick theme chosen meanwhile', async () => {
    const server = signedInServer()
    let release = () => {}
    server.mainColourGates.push(new Promise<void>((resolve) => { release = resolve }))
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    const button = screen.getByLabelText('Button colour')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(button, '#aa2244')
      button.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await waitFor(() => expect(server.mainColourRequests).toHaveLength(1))
    await userEvent.click(screen.getByRole('radio', { name: /^Neon Party/ }))
    await act(async () => {
      release()
      await new Promise((resolve) => setTimeout(resolve, 50))
    })
    expect(previewVar('primary_bg')).toBe(presetById('neon_party').tokens.primary_bg)
    expect(screen.getByRole('radio', { name: /^Neon Party/ })).toBeChecked()
  })

  it('background extraction sets the main colours from the image', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    await userEvent.upload(
      screen.getByLabelText('Background image'),
      new File([new Uint8Array(256)], 'bg.jpg', { type: 'image/jpeg' }),
    )
    expect(await screen.findByText('Colors extracted from background')).toBeInTheDocument()
    expect(screen.getByLabelText('Button colour')).toHaveValue(
      (server.extractResult.tokens.primary_bg ?? '').toLowerCase(),
    )
    expect(screen.getByLabelText('Text colour')).toHaveValue((server.extractResult.tokens.heading ?? '').toLowerCase())
  })
})
