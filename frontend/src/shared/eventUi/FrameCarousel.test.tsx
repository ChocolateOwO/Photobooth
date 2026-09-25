import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { FrameCarousel } from './FrameCarousel'
import { planSummary, type GalleryFrame } from './framePlan'

const STRIP = { template_key: 'strip_2x6', layout_label: '2×6', captures: 6, output_label: '2 strips' }
const P34 = { template_key: 'print_3x4', layout_label: '3×4', captures: 2, output_label: null }
const P46 = { template_key: 'print_4x6', layout_label: '4×6', captures: 4, output_label: null }

function frame(id: string, name: string, plan: GalleryFrame['plan']): GalleryFrame {
  return { id, name, plan, previewUrl: `/api/booth/frames/${id}/preview.jpg?v=1` }
}

const FRAMES = [
  frame('a', 'Gold party', P34),
  frame('b', 'Wide one', P46),
  frame('c', 'Night strip', STRIP),
  frame('d', 'Paper strip', STRIP),
]

/** jsdom has no layout: give the track a height so scroll positions mean something. */
const SLIDE_HEIGHT = 600

function renderCarousel(props: Partial<Parameters<typeof FrameCarousel>[0]> = {}) {
  const onConfirm = vi.fn()
  const onStart = vi.fn()
  const onChooseAgain = vi.fn()
  const onCancel = vi.fn()
  const view = render(
    <FrameCarousel
      frames={FRAMES}
      allowSurprise={false}
      selectedId={null}
      onConfirm={onConfirm}
      onStart={onStart}
      onChooseAgain={onChooseAgain}
      onCancel={onCancel}
      {...props}
    />,
  )
  Object.defineProperty(track(), 'clientHeight', { value: SLIDE_HEIGHT, configurable: true })
  return { ...view, onConfirm, onStart, onChooseAgain, onCancel }
}

function track(): HTMLElement {
  return screen.getByRole('list', { name: 'Choose your frame' })
}

function slides(): HTMLElement[] {
  return screen.getAllByTestId('frame-slide')
}

/** The frame the carousel has settled on: the only one that can be chosen. */
function currentSlide(): HTMLElement {
  const found = slides().filter((slide) => slide.hasAttribute('data-current'))
  expect(found).toHaveLength(1)
  return found[0] as HTMLElement
}

function position(): string {
  return within(currentSlide()).getByText(/^\d+ of \d+$/).textContent ?? ''
}

/** A swipe or the mouse wheel: the browser scrolls and snaps, then the carousel follows. */
function scrollToSlide(index: number) {
  const el = track()
  el.scrollTop = index * SLIDE_HEIGHT
  fireEvent.scroll(el)
}

describe('FrameCarousel (participants)', () => {
  it('shows one frame at a time, not a grid of cards', () => {
    renderCarousel()
    expect(screen.queryByRole('list', { name: 'Frames' })).toBeNull() // the old grid is gone
    expect(slides()).toHaveLength(FRAMES.length)
    expect(slides().filter((s) => s.hasAttribute('data-current'))).toHaveLength(1)
    // The current frame carries its name, size, summary, one big button and its position.
    const slide = currentSlide()
    expect(within(slide).getByText('Gold party')).toBeInTheDocument()
    expect(within(slide).getByText(planSummary(P34))).toBeInTheDocument()
    expect(within(slide).getByRole('button', { name: 'Use this frame' })).toBeInTheDocument()
    expect(position()).toBe('1 of 4')
    // Only the frame in view can be reached; the others are scenery until they are in view.
    expect(screen.getAllByRole('button', { name: 'Use this frame' })).toHaveLength(1)
    expect(slides()[1]).toHaveAttribute('inert')
    // The sample image is shown whole, in its own proportions.
    const image = within(slide).getByRole('img', { name: 'Gold party with sample photos' })
    expect(image).toHaveClass(/image/)
  })

  it('only the frame in view and its neighbours load an image', () => {
    renderCarousel()
    expect(screen.getAllByRole('img').map((img) => img.getAttribute('src'))).toEqual([
      FRAMES[0]?.previewUrl,
      FRAMES[1]?.previewUrl,
    ])
    scrollToSlide(3)
    expect(screen.getAllByRole('img').map((img) => img.getAttribute('src'))).toEqual([
      FRAMES[2]?.previewUrl,
      FRAMES[3]?.previewUrl,
    ])
  })

  it('Next, Previous, the arrow keys and scrolling all move one frame at a time', async () => {
    renderCarousel()
    const next = screen.getByRole('button', { name: 'Next frame' })
    const previous = screen.getByRole('button', { name: 'Previous frame' })
    expect(previous).toBeDisabled()

    await userEvent.click(next)
    expect(position()).toBe('2 of 4')
    expect(within(currentSlide()).getByText('Wide one')).toBeInTheDocument()
    await userEvent.click(previous)
    expect(position()).toBe('1 of 4')

    // Keyboard: Down/Up (and End/Home) move through the frames.
    fireEvent.keyDown(track(), { key: 'ArrowDown' })
    expect(position()).toBe('2 of 4')
    fireEvent.keyDown(track(), { key: 'ArrowUp' })
    expect(position()).toBe('1 of 4')
    fireEvent.keyDown(track(), { key: 'End' })
    expect(position()).toBe('4 of 4')
    expect(screen.getByRole('button', { name: 'Next frame' })).toBeDisabled()

    // A swipe or the wheel scrolls the track; the carousel follows where it settled.
    scrollToSlide(2)
    expect(position()).toBe('3 of 4')
    expect(within(currentSlide()).getByText('Night strip')).toBeInTheDocument()
  })

  it('announces the frame in view and moves with the position dots', async () => {
    renderCarousel()
    const live = screen.getAllByRole('status')[0] as HTMLElement
    expect(live).toHaveTextContent('Gold party, 3×4 • 2 photos, 1 of 4')
    await userEvent.click(screen.getByRole('button', { name: 'Show Paper strip' }))
    expect(position()).toBe('4 of 4')
    expect(live).toHaveTextContent('Paper strip, 2×6 • 6 photos • 2 strips, 4 of 4')
    expect(screen.getByRole('button', { name: 'Show Paper strip' })).toHaveAttribute('aria-current', 'true')
  })

  it('hides the first-use hint once the participant moves', async () => {
    renderCarousel()
    expect(screen.getByText('Swipe or scroll to see the next frame')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next frame' }))
    expect(screen.queryByText('Swipe or scroll to see the next frame')).toBeNull()
  })

  it('a size filter shows only that size and starts again at its first frame', async () => {
    renderCarousel()
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['All', '3×4', '4×6', '2×6'])
    fireEvent.keyDown(track(), { key: 'End' })
    expect(position()).toBe('4 of 4')

    await userEvent.click(screen.getByRole('tab', { name: '2×6' }))
    expect(slides()).toHaveLength(2)
    expect(position()).toBe('1 of 2')
    expect(within(currentSlide()).getByText('Night strip')).toBeInTheDocument() // the stable order
    expect(screen.queryByText('Gold party')).toBeNull()
    expect(track().scrollTop).toBe(0)
  })

  it('moving never chooses a frame; only "Use this frame" does', async () => {
    const { onConfirm } = renderCarousel()
    scrollToSlide(1)
    await userEvent.click(screen.getByRole('button', { name: 'Next frame' }))
    fireEvent.keyDown(track(), { key: 'ArrowDown' })
    await userEvent.click(screen.getByRole('tab', { name: '2×6' }))
    expect(onConfirm).not.toHaveBeenCalled()

    await userEvent.click(within(currentSlide()).getByRole('button', { name: 'Use this frame' }))
    expect(onConfirm).toHaveBeenCalledWith(FRAMES[2])
  })

  it('moving away abandons a confirmation that is still on its way', async () => {
    const { onCancel } = renderCarousel()
    await userEvent.click(within(currentSlide()).getByRole('button', { name: 'Use this frame' }))
    expect(onCancel).not.toHaveBeenCalled()
    scrollToSlide(2)
    expect(onCancel).toHaveBeenCalled()
  })

  it('opens on the frame chosen earlier in this session', () => {
    renderCarousel({ startAtId: 'c' })
    expect(position()).toBe('3 of 4')
    expect(within(currentSlide()).getByText('Night strip')).toBeInTheDocument()
  })

  it('shows the selection with Start and a way to choose again', async () => {
    const { onStart, onChooseAgain } = renderCarousel({ selectedId: 'd' })
    const bar = screen.getByText(/^Selected:/).closest('[role="status"]') as HTMLElement
    expect(bar).toHaveTextContent('Selected: Paper strip')
    await userEvent.click(within(bar).getByRole('button', { name: 'Start with this frame' }))
    expect(onStart).toHaveBeenCalledWith(FRAMES[3])
    await userEvent.click(within(bar).getByRole('button', { name: 'Choose a different frame' }))
    expect(onChooseAgain).toHaveBeenCalled()
  })

  it('a single frame needs no navigation', () => {
    renderCarousel({ frames: [FRAMES[0] as GalleryFrame], allowSurprise: true })
    expect(screen.getByRole('heading', { name: 'Choose your frame' })).toBeInTheDocument()
    expect(slides()).toHaveLength(1)
    expect(position()).toBe('1 of 1')
    expect(screen.getByRole('button', { name: 'Next frame' })).toBeDisabled()
    expect(screen.queryByText('Surprise me')).toBeNull() // needs two or more frames
    expect(screen.queryByText('Swipe or scroll to see the next frame')).toBeNull()
  })

  it('"Surprise me" moves to a frame without choosing it', async () => {
    const { onConfirm } = renderCarousel({ allowSurprise: true, random: () => 0.99 })
    await userEvent.click(screen.getByRole('button', { name: 'Surprise me' }))
    expect(position()).toBe('4 of 4')
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('never mentions where frames come from or admin actions', () => {
    renderCarousel({ allowSurprise: true })
    const text = document.body.textContent ?? ''
    for (const word of ['Built-in', 'Uploaded', 'Replace', 'Rename', 'Delete', 'px']) {
      expect(text).not.toContain(word)
    }
  })

  it('a failed image offers Retry without choosing that frame (P5R2-003)', async () => {
    vi.useFakeTimers()
    try {
      const { onConfirm } = renderCarousel()
      // The automatic retries run out (1, 2 and 4 s), then a Retry control appears.
      for (const wait of [1000, 2000, 4000]) {
        fireEvent.error(document.querySelector('img') as HTMLImageElement)
        act(() => {
          vi.advanceTimersByTime(wait)
        })
      }
      fireEvent.error(document.querySelector('img') as HTMLImageElement)
      const retry = screen.getAllByRole('button', { name: /^Retry/ })[0] as HTMLElement
      fireEvent.click(retry)
      expect(onConfirm).not.toHaveBeenCalled()
      expect(position()).toBe('1 of 4')
    } finally {
      vi.useRealTimers()
    }
  })
})
