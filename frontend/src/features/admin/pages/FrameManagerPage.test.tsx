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

function card(name: string): HTMLElement {
  const match = screen
    .getAllByTestId('frame-card')
    .find((element) => within(element).queryByRole('heading', { name }) !== null)
  if (!match) throw new Error(`no frame card for ${name}`)
  return match
}

describe('FrameManagerPage', () => {
  it('explains that frames are made outside the app and offers the guides', async () => {
    renderAdmin('/admin/frames', { server: signedInServer() })
    expect(await screen.findByRole('heading', { name: 'Frames' })).toBeInTheDocument()
    expect(
      screen.getByText(
        'Design frames in your own software, then upload the finished PNG here. This app never edits your file.',
      ),
    ).toBeInTheDocument()
    // One section per approved layout, each with its downloads and requirements.
    for (const layout of ['2x6 photo strip', '4x6 print']) {
      expect(await screen.findByRole('heading', { name: layout })).toBeInTheDocument()
    }
    const guides = await screen.findAllByRole('link', { name: 'Download guide image' })
    expect(guides[0]).toHaveAttribute('href', '/api/templates/strip_2x6/guide.png')
    const blanks = screen.getAllByRole('link', { name: 'Download blank canvas' })
    expect(blanks[0]).toHaveAttribute('href', '/api/templates/strip_2x6/blank.png')
    expect((await screen.findAllByText(/Size: exactly 600 x 1800 px/)).length).toBe(2)
    expect(
      (await screen.findAllByText(/File: PNG with transparency \(RGBA\), not animated\./)).length,
    ).toBe(2)
    expect(screen.getAllByText('No frames uploaded for this layout yet.')).toHaveLength(2)
    // There is no frame editor anywhere on the page.
    expect(screen.queryByRole('button', { name: /draw|design|edit frame/i })).toBeNull()
  })

  it('uploads a frame and shows the file and a sample preview', async () => {
    const server = signedInServer()
    renderAdmin('/admin/frames', { server })
    const names = await screen.findAllByLabelText('Frame name')
    await userEvent.type(names[0] as HTMLElement, 'Gold border')
    await userEvent.upload(screen.getAllByLabelText('Frame PNG file')[0] as HTMLElement, png())
    await userEvent.click(screen.getAllByRole('button', { name: 'Upload frame' })[0] as HTMLElement)

    expect(await screen.findByRole('status')).toHaveTextContent('Gold border was added.')
    const frame = server.customFrames()[0]
    expect(frame?.template_key).toBe('strip_2x6')
    const gold = card('Gold border')
    expect(within(gold).getByRole('img', { name: 'Gold border frame file' })).toHaveAttribute(
      'src',
      `/api/admin/frames/${frame?.id ?? ''}/content?v=${frame?.sha256 ?? ''}`,
    )
    const preview = within(gold).getByRole('img', { name: 'Gold border sample output' })
    expect(preview).toHaveAttribute(
      'src',
      `/api/admin/frames/${frame?.id ?? ''}/preview/1.jpg?v=${frame?.sha256 ?? ''}`,
    )
    expect(preview).toHaveAttribute('loading', 'lazy')
    expect(within(gold).getByText('Sample output with placeholder photos')).toBeInTheDocument()
    expect(within(gold).getByText('600 × 1800 px')).toBeInTheDocument()
    expect(screen.getAllByLabelText('Frame name')[0]).toHaveValue('') // cleared for the next one
  })

  it('refuses a file that is not a PNG, an oversized file and a missing name', async () => {
    const server = signedInServer()
    renderAdmin('/admin/frames', { server })
    const fileInput = (await screen.findAllByLabelText('Frame PNG file'))[0] as HTMLElement
    await userEvent.upload(fileInput, new File(['x'], 'f.jpg', { type: 'image/jpeg' }), {
      applyAccept: false,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('The frame must be a PNG file.')

    await userEvent.upload(fileInput, png('big.png', 10 * 1024 * 1024 + 1))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The frame must be 10 MB or smaller.',
    )

    await userEvent.upload(fileInput, png())
    await userEvent.click(screen.getAllByRole('button', { name: 'Upload frame' })[0] as HTMLElement)
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a frame name.')
    expect(server.customFrames()).toHaveLength(0)
  })

  it('shows the server reason when a frame is rejected or already exists', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Gold')
    renderAdmin('/admin/frames', { server })
    await userEvent.type(
      (await screen.findAllByLabelText('Frame name'))[0] as HTMLElement,
      'Gold',
    )
    await userEvent.upload(screen.getAllByLabelText('Frame PNG file')[0] as HTMLElement, png())
    await userEvent.click(screen.getAllByRole('button', { name: 'Upload frame' })[0] as HTMLElement)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      "A frame called 'Gold' already exists for this layout.",
    )
  })

  it('shows validation warnings recorded with a frame', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Lab profile', ['The frame uses the colour profile Lab.'])
    renderAdmin('/admin/frames', { server })
    expect(await screen.findByText('The frame uses the colour profile Lab.')).toBeInTheDocument()
  })

  it('replaces the file of an existing frame', async () => {
    const server = signedInServer()
    const frame = server.seedFrame('strip_2x6', 'Gold')
    renderAdmin('/admin/frames', { server })
    await screen.findByRole('heading', { name: 'Gold' })
    await userEvent.upload(screen.getByLabelText('Replace file for Gold'), png('new.png', 999))
    await waitFor(() => expect(server.frames.get(frame.id)?.bytes).toBe(999))
    expect(server.frames.get(frame.id)?.name).toBe('Gold') // same frame, new file
    // The new file has a new sha256, so both images get new URLs and never show the old file.
    const updated = server.frames.get(frame.id)?.sha256 ?? ''
    expect(updated).not.toBe(frame.sha256)
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'Gold frame file' })).toHaveAttribute(
        'src',
        `/api/admin/frames/${frame.id}/content?v=${updated}`,
      ),
    )
    expect(screen.getByRole('img', { name: 'Gold sample output' })).toHaveAttribute(
      'src',
      `/api/admin/frames/${frame.id}/preview/1.jpg?v=${updated}`,
    )
  })

  it('says it is loading instead of "no frames" until the list arrives (P5-005)', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Gold')
    let release = () => {}
    server.frameListGate = new Promise<void>((resolve) => {
      release = resolve
    })
    renderAdmin('/admin/frames', { server })
    expect((await screen.findAllByText('Loading frames…')).length).toBe(2)
    expect(screen.queryByText('No frames uploaded for this layout yet.')).toBeNull()
    release()
    expect(await screen.findByRole('heading', { name: 'Gold' })).toBeInTheDocument()
    expect(screen.queryByText('Loading frames…')).toBeNull()
  })

  it('reports a failed frame list with a retry instead of an empty library (P5-005)', async () => {
    const server = signedInServer()
    server.seedFrame('strip_2x6', 'Gold')
    server.frameListFailures = 1
    renderAdmin('/admin/frames', { server })
    expect(await screen.findByText('The uploaded frames could not be loaded.')).toBeInTheDocument()
    expect(screen.queryByText('No frames uploaded for this layout yet.')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Gold' })).toBeInTheDocument()
    expect(screen.queryByText('The uploaded frames could not be loaded.')).toBeNull()
  })

  it('loads the previews of a library larger than the render queue lazily (P5-006)', async () => {
    const server = signedInServer()
    for (let n = 1; n <= 6; n++) server.seedFrame('strip_2x6', `Frame ${n}`)
    renderAdmin('/admin/frames', { server })
    await screen.findByRole('heading', { name: 'Frame 6' })
    const previews = screen.getAllByRole('img', { name: /sample output$/ })
    expect(previews).toHaveLength(6 + 6) // six uploads plus the six built-in frames
    for (const preview of previews) expect(preview).toHaveAttribute('loading', 'lazy')
  })

  it('renames a frame', async () => {
    const server = signedInServer()
    const frame = server.seedFrame('strip_2x6', 'Gold')
    renderAdmin('/admin/frames', { server })
    await userEvent.click(await screen.findByRole('button', { name: 'Rename Gold' }))
    const input = within(card('Gold')).getByLabelText('Frame name')
    await userEvent.clear(input)
    await userEvent.type(input, 'Silver edge')
    await userEvent.click(screen.getByRole('button', { name: 'Save name' }))
    await waitFor(() => expect(server.frames.get(frame.id)?.name).toBe('Silver edge'))
  })

  it('asks before deleting and reports when a profile still uses the frame', async () => {
    const server = signedInServer()
    const frame = server.seedFrame('strip_2x6', 'Gold')
    server.framesInUse.set(frame.id, 'Wedding')
    renderAdmin('/admin/frames', { server })

    await userEvent.click(await screen.findByRole('button', { name: 'Delete Gold' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: 'Delete Gold?' })).toBeInTheDocument()
    expect(
      within(dialog).getByText(
        'The file is removed from this booth. Event Profiles that use it must pick another frame first.',
      ),
    ).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(server.customFrames()).toHaveLength(1)

    await userEvent.click(screen.getByRole('button', { name: 'Delete Gold' }))
    await userEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete frame' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'this frame is still used by: Wedding',
    )
    expect(server.customFrames()).toHaveLength(1)

    server.framesInUse.delete(frame.id)
    await userEvent.click(screen.getByRole('button', { name: 'Delete Gold' }))
    await userEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete frame' }),
    )
    await waitFor(() => expect(server.customFrames()).toHaveLength(0))
  })
})
