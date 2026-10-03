import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClientProvider } from '../../shared/api/ApiClientContext'
import { createApiClient } from '../../shared/api/client'
import { BoothErrorBoundary, Reconnecting } from './BoothSafety'
import { BoothShell } from './BoothShell'
import { BoothServicesContext, type BoothServices } from './boothServices'
import { CHECK_DEADLINE_MS, settleWithin, useKioskMode, useServerReachable } from './kiosk'

/**
 * Phase 12: the booth as a kiosk. Accidental input does nothing harmful, a lost server is said
 * plainly and waited out, and a screen that fails offers a way back instead of a blank page.
 */

function pointer(type: 'pointerdown' | 'pointerup', pointerType: string): Event {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'pointerType', { value: pointerType })
  return event
}

describe('settle within', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('gives up waiting on work that never answers, and never fails', async () => {
    let outcome: string | undefined
    void settleWithin(new Promise(() => undefined), 4000).then((value) => (outcome = value))
    await act(async () => {
      vi.advanceTimersByTime(3_900)
    })
    expect(outcome).toBeUndefined()
    await act(async () => {
      vi.advanceTimersByTime(200)
    })
    expect(outcome).toBe('late')
    await expect(settleWithin(Promise.reject(new Error('refused')), 4000)).resolves.toBe('done')
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

  it('asks for fullscreen when the browser allows it: a finger lifting, a mouse pressing', () => {
    renderHook(() => useKioskMode(true))
    document.body.dispatchEvent(pointer('pointerdown', 'touch'))
    expect(requested).toBe(0) // touch-down carries no permission to go fullscreen (P12-R3)
    document.body.dispatchEvent(pointer('pointerup', 'touch'))
    expect(requested).toBe(1)
    document.body.dispatchEvent(pointer('pointerup', 'pen'))
    expect(requested).toBe(2)
    document.body.dispatchEvent(pointer('pointerup', 'mouse'))
    expect(requested).toBe(2) // a mouse grants it on press, not on release
    document.body.dispatchEvent(pointer('pointerdown', 'mouse'))
    expect(requested).toBe(3)
  })

  it('an organizer test never asks for fullscreen', () => {
    renderHook(() => useKioskMode(false))
    document.body.dispatchEvent(pointer('pointerup', 'touch'))
    document.body.dispatchEvent(pointer('pointerdown', 'mouse'))
    expect(requested).toBe(0)
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

  it('a server that takes the request but never answers is lost too, and checks never pile up', async () => {
    let calls = 0
    let hanging = true
    const check = () => {
      calls += 1
      return hanging ? new Promise<void>(() => undefined) : Promise.resolve()
    }
    const { result } = renderHook(() => useServerReachable(check))
    await act(async () => {
      vi.advanceTimersByTime(5_000) // a check starts and hangs…
    })
    expect(calls).toBe(1)
    await act(async () => {
      window.dispatchEvent(new Event('offline')) // …so a second one does not start beside it
    })
    expect(calls).toBe(1)
    await act(async () => {
      vi.advanceTimersByTime(CHECK_DEADLINE_MS + 10) // …until its time runs out: one miss
    })
    expect(result.current).toBe(true)
    await act(async () => {
      vi.advanceTimersByTime(1_000) // the next check starts
    })
    await act(async () => {
      vi.advanceTimersByTime(CHECK_DEADLINE_MS + 10) // and runs out too: two misses
    })
    expect(calls).toBe(2)
    expect(result.current).toBe(false)
    hanging = false
    // Only just past the next check: a fake clock jumping further would also pass that check's
    // deadline before its (immediate) answer is seen, which a real clock never does.
    await act(async () => {
      vi.advanceTimersByTime(1_000)
    })
    await act(async () => {
      await Promise.resolve()
    })
    expect(calls).toBe(3)
    expect(result.current).toBe(true)
  })
})

describe('the booth shell while the server is lost', () => {
  const testBooth: BoothServices = {
    isTest: true,
    key: ['booth', 'test'],
    menu: () => Promise.reject(new Error('not used')),
    startVisit: () => Promise.reject(new Error('not used')),
    go: () => undefined,
  }

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('covers the screen, takes no input under the cover, and gives the focus back', async () => {
    let up = true
    const fetcher = async () =>
      up
        ? new Response(JSON.stringify({ status: 'ok', instance: 'dummy', database: 'ok' }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          })
        : Promise.reject(new TypeError('Failed to fetch'))
    let pressed = 0
    render(
      <ApiClientProvider client={createApiClient(fetcher)}>
        <MemoryRouter>
          <BoothServicesContext.Provider value={testBooth}>
            <BoothShell>
              <button type="button" onClick={() => (pressed += 1)}>
                Make my photos
              </button>
            </BoothShell>
          </BoothServicesContext.Provider>
        </MemoryRouter>
      </ApiClientProvider>,
    )
    const button = screen.getByRole('button', { name: 'Make my photos' })
    button.focus()
    up = false
    for (let check = 0; check < 2; check += 1) {
      await act(async () => {
        vi.advanceTimersByTime(5_100)
      })
    }
    const cover = screen.getByTestId('booth-offline')
    expect(screen.getByTestId('booth-screen')).toHaveAttribute('inert')
    expect(document.activeElement).toBe(cover)
    expect(screen.getByTestId('booth-shell')).toContainElement(button) // the visit stays mounted

    up = true
    await act(async () => {
      vi.advanceTimersByTime(5_100)
    })
    expect(screen.queryByTestId('booth-offline')).toBeNull()
    expect(screen.getByTestId('booth-screen')).not.toHaveAttribute('inert')
    expect(document.activeElement).toBe(button)
    fireEvent.click(button)
    expect(pressed).toBe(1)
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
