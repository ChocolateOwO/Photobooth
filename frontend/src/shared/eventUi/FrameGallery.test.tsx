import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { FrameGallery } from './FrameGallery'
import { planSummary, type GalleryFrame } from './framePlan'

const STRIP = { template_key: 'strip_2x6', layout_label: '2×6', captures: 6, output_label: '2 strips' }
const P34 = { template_key: 'print_3x4', layout_label: '3×4', captures: 2, output_label: null }
const P46 = { template_key: 'print_4x6', layout_label: '4×6', captures: 4, output_label: null }

function frame(id: string, name: string, plan: GalleryFrame['plan']): GalleryFrame {
  return { id, name, plan, previewUrl: `/api/booth/frames/${id}/preview.jpg?v=1` }
}

const FRAMES = [
  frame('a', 'Gold party', P34),
  frame('b', 'Night strip', STRIP),
  frame('c', 'Paper strip', STRIP),
]

function renderGallery(props: Partial<Parameters<typeof FrameGallery>[0]> = {}) {
  const onConfirm = vi.fn()
  const onStart = vi.fn()
  const onChooseAgain = vi.fn()
  const view = render(
    <FrameGallery
      frames={FRAMES}
      allowSurprise={false}
      selectedId={null}
      onConfirm={onConfirm}
      onStart={onStart}
      onChooseAgain={onChooseAgain}
      {...props}
    />,
  )
  return { ...view, onConfirm, onStart, onChooseAgain }
}

function cards() {
  return within(screen.getByRole('list', { name: 'Frames' })).getAllByRole('button')
}

describe('FrameGallery (participants)', () => {
  it('summarises what each frame means for the session', () => {
    expect(planSummary(STRIP)).toBe('2×6 • 6 photos • 2 strips')
    expect(planSummary(P34)).toBe('3×4 • 2 photos')
    expect(planSummary(P46)).toBe('4×6 • 4 photos')
  })

  it('shows every frame in the given order, starting on All, with tabs only for used layouts', async () => {
    renderGallery()
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['All', '3×4', '2×6'])
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(cards().map((c) => c.textContent)).toEqual([
      expect.stringContaining('Gold party'),
      expect.stringContaining('Night strip'),
      expect.stringContaining('Paper strip'),
    ])
    // Cards show the rendered sample with photos, not the raw frame file.
    const images = document.querySelectorAll('img')
    expect([...images].map((img) => img.getAttribute('src'))).toEqual(
      FRAMES.map((f) => f.previewUrl),
    )
    await userEvent.click(screen.getByRole('tab', { name: '2×6' }))
    expect(cards()).toHaveLength(2)
    expect(screen.queryByText('Gold party')).toBeNull()
  })

  it('tapping a card opens a bigger preview; only "Use this frame" selects it', async () => {
    const { onConfirm } = renderGallery()
    await userEvent.click(cards()[1] as HTMLElement)
    const dialog = screen.getByRole('dialog', { name: 'Night strip' })
    expect(within(dialog).getByText('2×6 • 6 photos • 2 strips')).toBeInTheDocument()
    expect(within(dialog).getByRole('img', { name: 'Night strip with sample photos' })).toBeInTheDocument()
    expect(onConfirm).not.toHaveBeenCalled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Back' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(onConfirm).not.toHaveBeenCalled()

    await userEvent.click(cards()[1] as HTMLElement)
    await userEvent.click(screen.getByRole('button', { name: 'Use this frame' }))
    expect(onConfirm).toHaveBeenCalledWith(FRAMES[1])
  })

  it('shows the selection with Start and a way to choose again', async () => {
    const { onStart, onChooseAgain } = renderGallery({ selectedId: 'c' })
    expect(screen.getByRole('button', { name: /Paper strip.*selected/ })).toHaveAttribute('aria-pressed', 'true')
    const bar = screen.getByRole('status')
    expect(bar).toHaveTextContent('Selected: Paper strip')
    await userEvent.click(within(bar).getByRole('button', { name: 'Start with this frame' }))
    expect(onStart).toHaveBeenCalledWith(FRAMES[2])
    await userEvent.click(within(bar).getByRole('button', { name: 'Choose a different frame' }))
    expect(onChooseAgain).toHaveBeenCalled()
  })

  it('a single frame still gets the selection screen', () => {
    renderGallery({ frames: [FRAMES[0] as GalleryFrame], allowSurprise: true })
    expect(screen.getByRole('heading', { name: 'Choose your frame' })).toBeInTheDocument()
    expect(cards()).toHaveLength(1)
    expect(screen.queryByText('Surprise me')).toBeNull() // needs two or more frames
  })

  it('"Surprise me" picks among the offered frames and opens the same confirmation', async () => {
    const { onConfirm } = renderGallery({ allowSurprise: true, random: () => 0.99 })
    await userEvent.click(screen.getByRole('button', { name: /Surprise me/ }))
    const dialog = screen.getByRole('dialog', { name: 'Paper strip' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Use this frame' }))
    expect(onConfirm).toHaveBeenCalledWith(FRAMES[2])
  })

  it('never mentions where frames come from or admin actions', () => {
    renderGallery({ allowSurprise: true })
    const text = document.body.textContent ?? ''
    for (const word of ['Built-in', 'Uploaded', 'Replace', 'Rename', 'Delete', 'px']) {
      expect(text).not.toContain(word)
    }
  })

  it('a failed preview can be retried without opening the frame (P5R2-003)', async () => {
    vi.useFakeTimers()
    try {
      renderGallery()
      // The automatic retries run out (1, 2 and 4 s), then a Retry control appears.
      for (const wait of [1000, 2000, 4000]) {
        fireEvent.error(document.querySelector('img') as HTMLImageElement)
        act(() => {
          vi.advanceTimersByTime(wait)
        })
      }
      fireEvent.error(document.querySelector('img') as HTMLImageElement)
      const retry = screen.getAllByRole('button', { name: /^Retry/ })[0] as HTMLElement
      expect(retry.closest('button[aria-pressed]')).toBeNull() // not nested in the card button
      fireEvent.click(retry)
      expect(screen.queryByRole('dialog')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
