import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BoothErrorBoundary, Reconnecting } from './BoothSafety'
import { useKioskMode, useServerReachable, useSingleFlight } from './kiosk'

/**
 * Phase 12: the booth as a kiosk. Accidental input does nothing harmful, a lost server is said
 * plainly and waited out, and a screen that fails offers a way back instead of a blank page.
 */

describe('single flight', () => {
  it('runs an action once however fast it is asked again', async () => {
    let calls = 0
    let finish: () => void = () => undefined
    const { result } = renderHook(() => useSingleFlight())
    const slow = () =>
      new Promise<void>((resolve) => {
        calls += 1
        finish = resolve
      })
    let first: Promise<void> = Promise.resolve()
    await act(async () => {
      first = result.current.run(slow)
      void result.current.run(slow) // the second tap, in the same frame
      void result.current.run(slow)
    })
    expect(calls).toBe(1)
    expect(result.current.pending).toBe(true)
    await act(async () => {
      finish()
      await first
    })
    expect(result.current.pending).toBe(false)
    await act(async () => {
      await result.current.run(async () => {
        calls += 1
      })
    })
    expect(calls).toBe(2) // once it is done, the next tap acts again
  })
})

describe('kiosk mode', () => {
  let requested = 0
  beforeEach(() => {
    requested = 0
    Object.defineProperty(document.documentElement, 'requestFullscreen', {
      configurable: true,
      value: () => {
        requested += 1
        return Promise.resolve()
      },
    })
    const meta = document.createElement('meta')
    meta.name = 'viewport'
    meta.content = 'width=device-width, initial-scale=1.0'
    document.head.appendChild(meta)
  })
  afterEach(() => {
    Reflect.deleteProperty(document.documentElement, 'requestFullscreen')
    document.querySelector('meta[name="viewport"]')?.remove()
  })

  it('refuses zoom, long-press menus and dragging, and puts everything back afterwards', () => {
    const { unmount } = renderHook(() => useKioskMode(true))
    const meta = document.querySelector('meta[name="viewport"]')
    expect(meta?.getAttribute('content')).toContain('user-scalable=no')
    const menu = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    document.body.dispatchEvent(menu)
    expect(menu.defaultPrevented).toBe(true)
    const drag = new Event('dragstart', { bubbles: true, cancelable: true })
    document.body.dispatchEvent(drag)
    expect(drag.defaultPrevented).toBe(true)

    unmount()
    expect(meta?.getAttribute('content')).toBe('width=device-width, initial-scale=1.0')
    const later = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    document.body.dispatchEvent(later)
    expect(later.defaultPrevented).toBe(false)
  })

  it('the real booth asks for fullscreen again on the next touch; a test does not', () => {
    const real = renderHook(() => useKioskMode(true))
    fireEvent.pointerDown(document.body)
    expect(requested).toBe(1)
    real.unmount()
    renderHook(() => useKioskMode(false))
    fireEvent.pointerDown(document.body)
    expect(requested).toBe(1)
  })
})

describe('server reachable', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('goes offline after two missed checks and back online at the first answer', async () => {
    let up = true
    const check = () => (up ? Promise.resolve() : Promise.reject(new TypeError('Failed to fetch')))
    const { result } = renderHook(() => useServerReachable(check))
    expect(result.current).toBe(true)
    up = false
    await act(async () => {
      vi.advanceTimersByTime(5_100)
    })
    expect(result.current).toBe(true) // one miss is not yet a lost server
    await act(async () => {
      vi.advanceTimersByTime(5_100)
    })
    expect(result.current).toBe(false)
    up = true
    await act(async () => {
      vi.advanceTimersByTime(5_100)
    })
    expect(result.current).toBe(true)
  })
})

describe('when things go wrong', () => {
  it('says the booth is reconnecting', () => {
    render(<Reconnecting />)
    expect(screen.getByTestId('booth-offline')).toHaveTextContent('The booth is reconnecting')
  })

  it('a screen that fails offers to start again, and starts again by itself', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let restarts = 0
    function Broken(): never {
      throw new Error('a drawing bug')
    }
    try {
      render(
        <BoothErrorBoundary onRestart={() => (restarts += 1)}>
          <Broken />
        </BoothErrorBoundary>,
      )
      expect(screen.getByTestId('booth-crashed')).toHaveTextContent('Sorry, something went wrong')
      await userEvent.click(screen.getByRole('button', { name: 'Start again' }))
      expect(restarts).toBe(1)
      await act(async () => {
        vi.advanceTimersByTime(30_500)
      })
      expect(restarts).toBe(2)
    } finally {
      quiet.mockRestore()
      vi.useRealTimers()
    }
  })
})
