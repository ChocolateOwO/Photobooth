import { screen, waitFor, within } from '@testing-library/react'
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

function jpeg(name = 'bg.jpg'): File {
  return new File([new Uint8Array(256)], name, { type: 'image/jpeg' })
}

function previewVar(key: string): string {
  const screenEl = within(screen.getByTestId('event-preview')).getByRole('group', {
    name: 'Kiosk screen preview',
  })
  return screenEl.style.getPropertyValue(tokenVar(key))
}

async function fillRequired() {
  await userEvent.type(await screen.findByLabelText('Profile name'), 'Themed')
  await userEvent.type(screen.getByLabelText('Title'), 'Welcome')
}

describe('event theme: quick presets', () => {
  it('starts a new profile with an accessible preset and shows every preset with colours', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    const midnight = await screen.findByRole('radio', { name: /^Midnight Blue/ })
    expect(midnight).toBeChecked()
    const radios = screen.getAllByRole('radio', { name: /./ }).filter((r) => r.getAttribute('name') === 'theme-preset')
    expect(radios.length).toBeGreaterThanOrEqual(6)
    expect(screen.getByRole('list', { name: 'Blush Wedding colours' }).children).toHaveLength(5)
    expect(screen.getByTestId('contrast-ok')).toHaveTextContent('All text and buttons meet WCAG AA contrast.')
    expect(previewVar('background')).toBe(presetById('midnight_blue').tokens.background)
  })

  it('applies the whole preset, not two colours, and saves it', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    await userEvent.click(screen.getByRole('radio', { name: /^Forest Fresh/ }))
    const forest = presetById('forest_fresh').tokens
    for (const key of ['background', 'surface', 'primary_bg', 'input_border', 'error_text']) {
      expect(previewVar(key)).toBe(forest[key])
    }
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    expect([...server.profiles.values()][0]?.settings.theme).toEqual({
      tokens: forest,
      source: 'preset',
      preset: 'forest_fresh',
      palette: [],
    })
  })
})

describe('event theme: advanced colours', () => {
  it('edits any token, warns about low contrast and resets to the preset', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    const heading = await screen.findByLabelText('Headings hex value')
    expect(screen.getByLabelText('Headings')).toHaveAccessibleDescription(
      'Titles such as the welcome heading.',
    )
    const background = presetById('midnight_blue').tokens.background ?? ''
    await userEvent.clear(heading)
    await userEvent.type(heading, background)
    expect(previewVar('heading')).toBe(background)
    const warning = await screen.findByTestId('contrast-warning')
    expect(warning).toHaveTextContent('Contrast warning')
    expect(warning).toHaveTextContent('Headings: contrast 1.0:1 is below 4.5:1')
    expect(screen.getAllByText('Low contrast').length).toBeGreaterThan(0)
    expect(screen.getByRole('radio', { name: /^Midnight Blue/ })).not.toBeChecked()

    await userEvent.click(screen.getByRole('button', { name: 'Reset to selected preset' }))
    expect(previewVar('heading')).toBe(presetById('midnight_blue').tokens.heading)
    expect(screen.queryByTestId('contrast-warning')).toBeNull()
    expect(screen.getByRole('radio', { name: /^Midnight Blue/ })).toBeChecked()

    // A hand-made colour is saved as it is (after the warning), marked custom.
    await userEvent.clear(screen.getByLabelText('Links hex value'))
    await userEvent.type(screen.getByLabelText('Links hex value'), '#FFAA00')
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    const saved = [...server.profiles.values()][0]?.settings.theme
    expect(saved?.tokens.link).toBe('#FFAA00')
    expect(saved?.source).toBe('custom')
    expect(saved?.preset).toBe('midnight_blue')
  })

  it('keeps an invalid hex draft out of the theme', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    const link = await screen.findByLabelText('Links hex value')
    const before = previewVar('link')
    await userEvent.clear(link)
    await userEvent.type(link, '#12')
    expect(previewVar('link')).toBe(before)
  })
})

describe('event theme: colours from the background', () => {
  it('extracts, shows the swatches, undoes, re-extracts and hands over to presets', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    expect(
      screen.getByText(/Upload a background image under Images and its colours are used/),
    ).toBeInTheDocument()

    await userEvent.upload(screen.getByLabelText('Background image'), jpeg())
    expect(await screen.findByText('Colors extracted from background')).toBeInTheDocument()
    const assetId = [...server.assets.keys()][0] ?? ''
    expect(server.extractedFrom).toEqual([assetId])
    const swatches = screen.getByRole('list', { name: 'Colours found in the background' })
    expect(within(swatches).getByText('#D946EF')).toBeInTheDocument()
    expect(previewVar('primary_bg')).toBe(server.extractResult.tokens.primary_bg)
    expect(screen.getByRole('radio', { name: /^Midnight Blue/ })).not.toBeChecked()

    await userEvent.click(screen.getByRole('button', { name: 'Undo extracted theme' }))
    expect(previewVar('primary_bg')).toBe(presetById('midnight_blue').tokens.primary_bg)
    expect(screen.getByRole('radio', { name: /^Midnight Blue/ })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Undo extracted theme' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Re-extract colors' }))
    await waitFor(() => expect(server.extractedFrom).toEqual([assetId, assetId]))
    expect(await screen.findByText('Colors extracted from background')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Choose a preset instead' }))
    expect(screen.getAllByRole('radio').find((r) => r.getAttribute('name') === 'theme-preset')).toHaveFocus()

    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    expect([...server.profiles.values()][0]?.settings.theme).toMatchObject({
      source: 'extracted',
      preset: null,
      palette: server.extractResult.palette,
    })
  })

  it('a replaced background gives a new extraction; a failure keeps the theme', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    const input = screen.getByLabelText('Background image')
    await userEvent.upload(input, jpeg('one.jpg'))
    await screen.findByText('Colors extracted from background')
    server.extractFailure = 'The background image could not be read.'
    await userEvent.upload(input, jpeg('two.jpg'))
    expect(await screen.findByText(/Colours could not be taken from the background/)).toBeInTheDocument()
    expect(server.extractedFrom).toHaveLength(2)
    expect(server.extractedFrom[0]).not.toBe(server.extractedFrom[1])
    // The first extracted theme stays; nothing silently changed.
    expect(previewVar('primary_bg')).toBe(server.extractResult.tokens.primary_bg)
  })

  it('a late extraction never overwrites a preset chosen meanwhile (P5R-002)', async () => {
    const server = signedInServer()
    let release = () => {}
    server.extractGates.push(new Promise<void>((resolve) => { release = resolve }))
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    await userEvent.upload(screen.getByLabelText('Background image'), jpeg())
    expect(await screen.findByText('Reading colours from the background…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled()
    await userEvent.click(screen.getByRole('radio', { name: /^Forest Fresh/ }))
    release()
    await waitFor(() => expect(screen.queryByText('Reading colours from the background…')).toBeNull())
    expect(previewVar('background')).toBe(presetById('forest_fresh').tokens.background)
    expect(screen.getByRole('radio', { name: /^Forest Fresh/ })).toBeChecked()
    expect(screen.queryByText('Colors extracted from background')).toBeNull()
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeEnabled()
  })

  it('answers arriving out of order leave the newest background in charge (P5R-002)', async () => {
    const server = signedInServer()
    const releases: (() => void)[] = []
    for (let i = 0; i < 2; i++) {
      server.extractGates.push(new Promise<void>((resolve) => releases.push(resolve)))
    }
    const older = { ...server.extractResult, palette: ['#111111'], tokens: { ...presetById('sunset_coral').tokens } }
    const newer = { ...server.extractResult, palette: ['#222222'], tokens: { ...presetById('neon_party').tokens } }
    renderAdmin('/admin/profiles/new', { server })
    await fillRequired()
    const input = screen.getByLabelText('Background image')
    await userEvent.upload(input, jpeg('a.jpg'))
    await waitFor(() => expect(server.extractedFrom).toHaveLength(1))
    await userEvent.upload(input, jpeg('b.jpg'))
    await waitFor(() => expect(server.extractedFrom).toHaveLength(2))
    server.extractResults.set(server.extractedFrom[0] ?? '', older)
    server.extractResults.set(server.extractedFrom[1] ?? '', newer)
    releases[1]?.() // the newer background answers first...
    expect(await screen.findByText('Colors extracted from background')).toBeInTheDocument()
    releases[0]?.() // ...and the older, late answer must be ignored
    await waitFor(() => expect(screen.queryByText('Reading colours from the background…')).toBeNull())
    expect(previewVar('background')).toBe(newer.tokens.background)
    expect(screen.getByText('#222222')).toBeInTheDocument()
    expect(screen.queryByText('#111111')).toBeNull()
  })

  it('a new profile with a failing frame list shows a stable error and retries only on request (P5R-003)', async () => {
    const server = signedInServer()
    server.frameListFailures = 100
    renderAdmin('/admin/profiles/new', { server })
    const alert = await screen.findByText(/The frames could not be loaded/)
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect(server.frameListRequests).toBeLessThanOrEqual(2)
    expect(screen.getByLabelText('Profile name')).toBeInTheDocument() // the form stays
    server.frameListFailures = 0
    await userEvent.click(
      within(alert.closest('[role="alert"]') as HTMLElement).getByRole('button', { name: 'Try again' }),
    )
    // The frames arrived: the first layout now gets its built-in default.
    await waitFor(() =>
      expect(screen.getByLabelText('Frame for 2x6 photo strip')).toHaveValue(
        server.builtin('midnight', 'strip_2x6').id,
      ),
    )
    expect(server.frameListRequests).toBeLessThanOrEqual(3)
  })

  it('never themes the admin pages themselves', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    await screen.findByRole('radio', { name: /^Midnight Blue/ })
    const heading = screen.getByRole('heading', { name: 'New Event Profile' })
    expect(heading.closest('[data-event-theme]')).toBeNull()
    expect(screen.getByRole('button', { name: 'Save profile' }).closest('[data-event-theme]')).toBeNull()
  })
})

describe('built-in frames in the frame manager', () => {
  it('labels built-in frames and offers no replace, rename or delete for them', async () => {
    renderAdmin('/admin/frames', { server: signedInServer() })
    const list = await screen.findByRole('list', { name: 'Built-in frames for 2x6 photo strip' })
    const cards = within(list).getAllByTestId('frame-card')
    expect(cards.map((c) => within(c).getByRole('heading').textContent)).toEqual([
      'Minimal Light',
      'Midnight',
      'Celebration Gold',
    ])
    for (const card of cards) {
      expect(within(card).getByText('Built-in')).toBeInTheDocument()
      expect(within(card).queryByRole('button', { name: /Replace|Rename|Delete/ })).toBeNull()
      expect(within(card).getByRole('img', { name: /sample output$/ })).toBeInTheDocument()
    }
    expect(screen.getAllByText('No frames uploaded for this layout yet.')).toHaveLength(2)
  })
})
