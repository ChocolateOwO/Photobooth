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

function png(name = 'frame.png', bytes = 256): File {
  return new File([new Uint8Array(bytes)], name, { type: 'image/png' })
}

function row(name: string): HTMLElement {
  const match = screen
    .getAllByTestId('frame-row')
    .find((element) => within(element).queryByRole('heading', { name }) !== null)
  if (!match) throw new Error(`no frame row for ${name}`)
  return match
}

async function openUpload() {
  await userEvent.click(await screen.findByRole('button', { name: 'Add frame' }))
  return screen.getByRole('dialog', { name: 'Add frame' })
}

async function upload(dialog: HTMLElement, name: string, file: File, layout?: string) {
  if (layout) await userEvent.selectOptions(within(dialog).getByLabelText('Layout'), layout)
  if (name) await userEvent.type(within(dialog).getByLabelText('Frame name'), name)
  await userEvent.upload(within(dialog).getByLabelText('Frame PNG file'), file)
  await userEvent.click(within(dialog).getByRole('button', { name: 'Upload frame' }))
}

describe('FrameManagerPage: compact layouts', () => {
  it('lists one compact row per layout and keeps the specification behind Details', async () => {
    renderAdmin('/admin/frames', { server: signedInServer() })
    expect(await screen.findByRole('heading', { name: 'Frames' })).toBeInTheDocument()
    expect(
      screen.getByText(
        'Design frames in your own software, then upload the finished PNG here. This app never edits your file.',
      ),
    ).toBeInTheDocument()
    const layouts = await screen.findAllByTestId('layout-row')
    expect(layouts).toHaveLength(2)
    const strip = layouts[0] as HTMLElement
    expect(strip).toHaveTextContent('2x6 photo strip')
    expect(strip).toHaveTextContent('2 × 6 in')
    expect(strip).toHaveTextContent('600 × 1800 px')
    // Nothing technical is inline, and the blank canvas download is gone.
    expect(screen.queryByText(/Size: exactly/)).toBeNull()
    expect(screen.queryByText(/DPI/)).toBeNull()
    expect(screen.queryByRole('link', { name: 'Download blank canvas' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Download guide image' })).toBeNull()
    expect(screen.queryByLabelText('Frame PNG file')).toBeNull() // no upload form per layout

    await userEvent.click(within(strip).getByRole('button', { name: 'Details of 2x6 photo strip' }))
    const details = screen.getByRole('dialog', { name: '2x6 photo strip: specification' })
    for (const text of [
      '2 × 6 in (portrait)',
      '600 × 1800 px',
      '300 DPI',
      'PNG with transparency (RGBA), sRGB, not animated, exactly this pixel size',
      'At least 95% transparent',
      '10 MB',
      'x 30, y 30, 540 × 1740 px',
      'x 30, y 1590, 540 × 180 px',
    ]) {
      expect(within(details).getByText(text)).toBeInTheDocument()
    }
    const slots = within(details).getByRole('table', { name: 'Photo slot coordinates (px)' })
    expect(within(slots).getAllByRole('row')).toHaveLength(4) // header + three photos
    expect(within(details).getByText('Size: exactly 600 x 1800 px.')).toBeInTheDocument()
    expect(within(details).getByRole('link', { name: 'Download guide image' })).toHaveAttribute(
      'href',
      '/api/templates/strip_2x6/guide.png',
    )
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(within(strip).getByRole('button', { name: 'Details of 2x6 photo strip' })).toHaveFocus()

    // There is no frame editor anywhere on the page.
    expect(screen.queryByRole('button', { name: /draw|design|edit frame/i })).toBeNull()
  })

  it('previews a layout guide in one large dialog', async () => {
    renderAdmin('/admin/frames', { server: signedInServer() })
    await userEvent.click(await screen.findByRole('button', { name: 'Preview of 4x6 print' }))
    const dialog = screen.getByRole('dialog', { name: '4x6 print: layout guide' })
    const images = within(dialog).getAllByRole('img')
    expect(images).toHaveLength(1)
    expect(images[0]).toHaveAttribute('src', '/api/templates/print_4x6/guide.png')
    expect(within(dialog).getByRole('link', { name: 'Download guide image' })).toBeInTheDocument()
  })
})

describe('FrameManagerPage: frame library', () => {
  it('shows each frame as one compact row with one thumbnail and icon actions', async () => {
    const server = signedInServer()
    const gold = server.seedFrame('strip_2x6', 'Gold')
    server.seedProfile({ name: 'Wedding', enabled_layouts: ['strip_2x6'] })
    renderAdmin('/admin/frames', { server })
    await screen.findByRole('heading', { name: 'Gold' })
    const goldRow = row('Gold')
    const images = within(goldRow).getAllByRole('img')
    expect(images).toHaveLength(1) // one rendered thumbnail, never the raw file as well
    expect(images[0]).toHaveAttribute('src', `/api/admin/frames/${gold.id}/preview/1.jpg?v=${gold.sha256}`)
    expect(images[0]).toHaveAttribute('loading', 'lazy')
    expect(within(goldRow).getByText('2×6 · 600 × 1800 px')).toBeInTheDocument()
    expect(within(goldRow).getByText('Uploaded')).toBeInTheDocument()
    expect(within(goldRow).getByTestId('frame-usage')).toHaveTextContent('Offered by: Wedding')
    for (const label of ['Details of Gold', 'Preview Gold', 'Rename Gold', 'Replace file for Gold', 'Delete Gold']) {
      expect(within(goldRow).getByRole('button', { name: label })).toBeInTheDocument()
    }
    expect(screen.getAllByTestId('frame-row')).toHaveLength(7) // six built-in frames and Gold
  })

  it('opens one large preview from the Preview button or the thumbnail', async () => {
    const server = signedInServer()
    const gold = server.seedFrame('strip_2x6', 'Gold')
    renderAdmin('/admin/frames', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Preview Gold' }))
    let dialog = screen.getByRole('dialog', { name: 'Gold' })
    const images = within(dialog).getAllByRole('img')
    expect(images).toHaveLength(1)
    expect(images[0]).toHaveAttribute('src', `/api/admin/frames/${gold.id}/preview/1.jpg?v=${gold.sha256}`)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()

    const thumbButton = row('Gold').querySelector('button[aria-hidden="true"]') as HTMLElement
    await userEvent.click(thumbButton)
    dialog = screen.getByRole('dialog', { name: 'Gold' })
    expect(within(dialog).getAllByRole('img')).toHaveLength(1)
  })

  it('shows frame details with usage, size and warnings', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Lab profile', ['The frame uses the colour profile Lab.'])
    server.seedProfile({ name: 'Wedding', enabled_layouts: ['strip_2x6'] })
    renderAdmin('/admin/frames', { server })
    // A warning is visible in the row itself.
    expect(await screen.findByText('The frame uses the colour profile Lab.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Details of Lab profile' }))
    const dialog = screen.getByRole('dialog', { name: 'Lab profile: details' })
    expect(within(dialog).getByText('Uploaded')).toBeInTheDocument()
    expect(within(dialog).getByText('Wedding')).toBeInTheDocument()
    expect(within(dialog).getByText('600 × 1800 px')).toBeInTheDocument()
  })

  it('searches the library, filters it with pills and keeps the selected pill distinct', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Gold rush')
    renderAdmin('/admin/frames', { server })
    await screen.findByRole('heading', { name: 'Gold rush' })
    const pills = screen.getByRole('group', { name: 'Show' })
    const all = within(pills).getByRole('button', { name: 'All' })
    expect(all).toHaveAttribute('aria-pressed', 'true')
    expect(within(pills).getAllByRole('button').filter((b) => b.getAttribute('aria-pressed') === 'true')).toHaveLength(1)

    await userEvent.click(within(pills).getByRole('button', { name: 'Uploaded' }))
    expect(screen.getAllByTestId('frame-row')).toHaveLength(1)
    expect(all).toHaveAttribute('aria-pressed', 'false')

    await userEvent.click(within(pills).getByRole('button', { name: 'Built-in' }))
    expect(screen.queryByRole('heading', { name: 'Gold rush' })).toBeNull()
    expect(screen.getAllByTestId('frame-row').every((r) => within(r).queryByText('Built-in'))).toBe(true)

    await userEvent.click(within(pills).getByRole('button', { name: '4×6' }))
    expect(screen.getAllByTestId('frame-row').every((r) => within(r).queryByText(/^4×6 ·/))).toBe(true)

    await userEvent.click(within(pills).getByRole('button', { name: 'All' }))
    await userEvent.type(screen.getByLabelText('Search by frame name'), 'gold')
    const names = screen.getAllByTestId('frame-row').map((r) => within(r).getByRole('heading').textContent)
    expect(names).toEqual(['Celebration Gold', 'Gold rush', 'Celebration Gold'])
  })

  it('moves between the filter pills with the arrow keys', async () => {
    renderAdmin('/admin/frames', { server: signedInServer() })
    const pills = await screen.findByRole('group', { name: 'Show' })
    const all = within(pills).getByRole('button', { name: 'All' })
    expect(all).toHaveAttribute('tabindex', '0')
    expect(within(pills).getByRole('button', { name: 'Uploaded' })).toHaveAttribute('tabindex', '-1')
    all.focus()
    await userEvent.keyboard('{ArrowRight}')
    const strip = within(pills).getByRole('button', { name: '2×6' })
    expect(strip).toHaveFocus()
    expect(strip).toHaveAttribute('aria-pressed', 'true')
    await userEvent.keyboard('{End}')
    expect(within(pills).getByRole('button', { name: 'Uploaded' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.keyboard('{Home}')
    expect(all).toHaveAttribute('aria-pressed', 'true')
  })

  it('says it is loading instead of "no frames" until the list arrives (P5-005)', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Gold')
    let release = () => {}
    server.frameListGate = new Promise<void>((resolve) => {
      release = resolve
    })
    renderAdmin('/admin/frames', { server })
    expect(await screen.findByText('Loading frames…')).toBeInTheDocument()
    expect(screen.queryByText(/No frames/)).toBeNull()
    release()
    expect(await screen.findByRole('heading', { name: 'Gold' })).toBeInTheDocument()
    expect(screen.queryByText('Loading frames…')).toBeNull()
  })

  it('reports a failed frame list with a retry instead of an empty library (P5-005)', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Gold')
    server.frameListFailures = 1
    renderAdmin('/admin/frames', { server })
    expect(await screen.findByText('The frames could not be loaded.')).toBeInTheDocument()
    expect(screen.queryByText(/No frames/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Gold' })).toBeInTheDocument()
    expect(screen.queryByText('The frames could not be loaded.')).toBeNull()
  })

  it('loads the thumbnails of a library larger than the render queue lazily (P5-006)', async () => {
    const server = signedInServer()
    for (let n = 1; n <= 6; n++) server.seedFrame('strip_2x6', `Frame ${n}`)
    renderAdmin('/admin/frames', { server })
    await screen.findByRole('heading', { name: 'Frame 6' })
    const previews = screen.getAllByRole('img', { name: /sample output$/ })
    expect(previews).toHaveLength(6 + 6) // six uploads plus the six built-in frames
    for (const preview of previews) expect(preview).toHaveAttribute('loading', 'lazy')
  })
})

describe('FrameManagerPage: add, replace, rename and delete', () => {
  it('uploads from one Add frame dialog with layout, name, file and guidance', async () => {
    const server = signedInServer()
    renderAdmin('/admin/frames', { server })
    expect(screen.queryByRole('dialog')).toBeNull()
    const dialog = await openUpload()
    expect(within(dialog).getByLabelText('Layout')).toHaveValue('strip_2x6')
    expect(within(dialog).getByTestId('upload-guidance')).toHaveTextContent('exactly 600 × 1800 px')
    await userEvent.selectOptions(within(dialog).getByLabelText('Layout'), 'print_4x6')
    expect(within(dialog).getByTestId('upload-guidance')).toHaveTextContent('exactly 1200 × 1800 px')
    await upload(dialog, 'Gold border', png())

    const done = await screen.findByRole('alertdialog', { name: 'Frame added' })
    expect(done).toHaveTextContent('Gold border was added.')
    expect(screen.queryByRole('dialog', { name: 'Add frame' })).toBeNull()
    expect(server.customFrames()[0]?.template_key).toBe('print_4x6')
    expect(row('Gold border')).toHaveTextContent('4×6 · 1200 × 1800 px')
  })

  it('refuses a file that is not a PNG, an oversized file and a missing name inside the dialog', async () => {
    const server = signedInServer()
    renderAdmin('/admin/frames', { server })
    const dialog = await openUpload()
    const fileInput = within(dialog).getByLabelText('Frame PNG file')
    await userEvent.upload(fileInput, new File(['x'], 'f.jpg', { type: 'image/jpeg' }), { applyAccept: false })
    expect(within(dialog).getByRole('alert')).toHaveTextContent('The frame must be a PNG file.')
    await userEvent.upload(fileInput, png('big.png', 10 * 1024 * 1024 + 1))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('The frame must be 10 MB or smaller.')
    await userEvent.upload(fileInput, png())
    await userEvent.click(within(dialog).getByRole('button', { name: 'Upload frame' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Enter a frame name.')
    expect(server.customFrames()).toHaveLength(0)
  })

  it('shows the server reason for a refused upload inside the dialog', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Gold')
    renderAdmin('/admin/frames', { server })
    const dialog = await openUpload()
    await upload(dialog, 'Gold', png())
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      "A frame called 'Gold' already exists for this layout.",
    )
  })

  it('replaces the file of an existing frame and confirms it in a pop-up', async () => {
    const server = signedInServer()
    const frame = server.seedFrame('strip_2x6', 'Gold')
    renderAdmin('/admin/frames', { server })
    await screen.findByRole('heading', { name: 'Gold' })
    await userEvent.upload(screen.getByLabelText('New PNG file for Gold'), png('new.png', 999))
    await waitFor(() => expect(server.frames.get(frame.id)?.bytes).toBe(999))
    expect(await screen.findByRole('alertdialog', { name: 'File replaced' })).toBeInTheDocument()
    expect(server.frames.get(frame.id)?.name).toBe('Gold') // same frame, new file
    const updated = server.frames.get(frame.id)?.sha256 ?? ''
    expect(updated).not.toBe(frame.sha256)
    await waitFor(() =>
      expect(within(row('Gold')).getByRole('img', { name: 'Gold sample output' })).toHaveAttribute(
        'src',
        `/api/admin/frames/${frame.id}/preview/1.jpg?v=${updated}`,
      ),
    )
  })

  it('reports a refused replacement file in a pop-up', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Gold')
    renderAdmin('/admin/frames', { server })
    await screen.findByRole('heading', { name: 'Gold' })
    await userEvent.upload(
      screen.getByLabelText('New PNG file for Gold'),
      new File(['x'], 'f.jpg', { type: 'image/jpeg' }),
      { applyAccept: false },
    )
    const message = await screen.findByRole('alertdialog', { name: 'The file was not replaced' })
    expect(message).toHaveTextContent('The frame must be a PNG file.')
  })

  it('renames a frame in a dialog', async () => {
    const server = signedInServer()
    const frame = server.seedFrame('strip_2x6', 'Gold')
    renderAdmin('/admin/frames', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Rename Gold' }))
    const dialog = screen.getByRole('dialog', { name: 'Rename Gold' })
    const input = within(dialog).getByLabelText('Frame name')
    expect(input).toHaveFocus()
    await userEvent.clear(input)
    await userEvent.type(input, 'Silver edge')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save name' }))
    await waitFor(() => expect(server.frames.get(frame.id)?.name).toBe('Silver edge'))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('asks before deleting and reports in a pop-up when a profile still uses the frame', async () => {
    const server = signedInServer()
    const frame = server.seedFrame('strip_2x6', 'Gold')
    server.framesInUse.set(frame.id, 'Wedding')
    renderAdmin('/admin/frames', { server })

    await userEvent.click(await screen.findByRole('button', { name: 'Delete Gold' }))
    let confirm = screen.getByRole('alertdialog', { name: 'Delete Gold?' })
    expect(
      within(confirm).getByText(
        'The file is removed from this booth and participants can no longer choose this frame.',
      ),
    ).toBeInTheDocument()
    expect(within(confirm).getByRole('button', { name: 'Cancel' })).toHaveFocus() // the safe choice
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(server.customFrames()).toHaveLength(1)

    await userEvent.click(screen.getByRole('button', { name: 'Delete Gold' }))
    confirm = screen.getByRole('alertdialog', { name: 'Delete Gold?' })
    await userEvent.click(within(confirm).getByRole('button', { name: 'Delete frame' }))
    const refused = await screen.findByRole('alertdialog', { name: 'Gold was not deleted' })
    expect(refused).toHaveTextContent('this frame is still used by: Wedding')
    expect(server.customFrames()).toHaveLength(1)
    await userEvent.click(within(refused).getByRole('button', { name: 'Close' }))

    server.framesInUse.delete(frame.id)
    await userEvent.click(screen.getByRole('button', { name: 'Delete Gold' }))
    await userEvent.click(
      within(screen.getByRole('alertdialog', { name: 'Delete Gold?' })).getByRole('button', { name: 'Delete frame' }),
    )
    await waitFor(() => expect(server.customFrames()).toHaveLength(0))
  })
})
