import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RetryingImage } from './RetryingImage'

const SRC = '/api/admin/frames/f1/preview/1.jpg?v=abc'

function image(): HTMLElement {
  return screen.getByAltText('Gold sample output') // also while hidden between attempts
}

describe('RetryingImage (P5-006)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('retries a busy preview with growing delays, then offers a visible Retry', () => {
    render(<RetryingImage src={SRC} alt="Gold sample output" />)
    expect(image()).toHaveAttribute('src', SRC)
    expect(image()).toHaveAttribute('loading', 'lazy')

    // The render queue was full (503): wait, then ask again with a fresh URL.
    fireEvent.error(image())
    expect(screen.getByText('Preparing the preview…')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(999)
    })
    expect(image()).toHaveAttribute('src', SRC)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(image()).toHaveAttribute('src', `${SRC}&retry=1`)
    expect(image()).toBeVisible()

    fireEvent.error(image())
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(image()).toHaveAttribute('src', `${SRC}&retry=2`)
    fireEvent.error(image())
    act(() => {
      vi.advanceTimersByTime(4000)
    })
    expect(image()).toHaveAttribute('src', `${SRC}&retry=3`)

    // Out of automatic retries: no broken image, a plain message and a button instead.
    fireEvent.error(image())
    expect(image()).not.toBeVisible()
    expect(
      screen.getByText('The preview could not be loaded. The booth may be busy.'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry Gold sample output' }))
    expect(image()).toHaveAttribute('src', `${SRC}&retry=4`)
    expect(image()).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Retry Gold sample output' })).toBeNull()
  })

  it('starts over when the source changes (a replaced frame file)', () => {
    const { rerender } = render(<RetryingImage src={SRC} alt="Gold sample output" />)
    fireEvent.error(image())
    rerender(<RetryingImage src="/api/admin/frames/f1/preview/1.jpg?v=new" alt="Gold sample output" />)
    expect(image()).toHaveAttribute('src', '/api/admin/frames/f1/preview/1.jpg?v=new')
    expect(image()).toBeVisible()
    expect(screen.queryByText('Preparing the preview…')).toBeNull()
  })

  it('adds the retry marker to a URL without a query string', () => {
    render(<RetryingImage src="/x.jpg" alt="Gold sample output" />)
    fireEvent.error(image())
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(image()).toHaveAttribute('src', '/x.jpg?retry=1')
  })
})
