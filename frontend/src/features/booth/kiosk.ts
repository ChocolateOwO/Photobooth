import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Kiosk behaviour for the booth's own display.
 *
 * A touchscreen kiosk gets every kind of accidental input: double taps, a palm resting on the
 * screen, a long press that opens a menu, a pinch that zooms the page, a stray Escape that leaves
 * fullscreen. These hooks keep the booth usable through all of them.
 */

/**
 * Runs an action at most once at a time: a second tap while the first is still being answered
 * does nothing (a ref, not state, so even two taps in the same frame can not both get through).
 * `pending` lets the screen show the button as busy.
 */
export function useSingleFlight(): {
  pending: boolean
  run: (action: () => Promise<unknown> | unknown) => Promise<void>
} {
  const flying = useRef(false)
  const [pending, setPending] = useState(false)
  const run = useCallback(async (action: () => Promise<unknown> | unknown) => {
    if (flying.current) return
    flying.current = true
    setPending(true)
    try {
      await action()
    } finally {
      flying.current = false
      setPending(false)
    }
  }, [])
  return { pending, run }
}

const NO_ZOOM = 'width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no'

function enterFullscreen(): void {
  const page = document.documentElement
  if (document.fullscreenElement || typeof page.requestFullscreen !== 'function') return
  try {
    void page.requestFullscreen().catch(() => undefined)
  } catch {
    // Refused (no gesture, or a browser without it): the booth still fills the window.
  }
}

/**
 * While the booth is on screen: no page zoom, no long-press menu, no dragging pictures out, and,
 * for the real booth (`fullscreen`), the next touch after fullscreen was left asks for it again.
 * Everything is put back when the booth is left (Admin keeps its normal behaviour).
 */
export function useKioskMode(fullscreen: boolean): void {
  useEffect(() => {
    const viewport = document.querySelector<HTMLMetaElement>('meta[name="viewport"]')
    const before = viewport?.getAttribute('content') ?? null
    viewport?.setAttribute('content', NO_ZOOM)

    const refuse = (event: Event) => event.preventDefault()
    const touched = () => {
      if (fullscreen) enterFullscreen()
    }
    document.addEventListener('contextmenu', refuse)
    document.addEventListener('dragstart', refuse)
    document.addEventListener('pointerdown', touched, { capture: true })
    return () => {
      if (viewport && before !== null) viewport.setAttribute('content', before)
      document.removeEventListener('contextmenu', refuse)
      document.removeEventListener('dragstart', refuse)
      document.removeEventListener('pointerdown', touched, { capture: true })
    }
  }, [fullscreen])
}

/** How often the booth checks it can still reach its own server, and after how many misses. */
const CHECK_EVERY_MS = 5000
const MISSES_BEFORE_OFFLINE = 2

/**
 * Whether the booth can reach its server. Two missed checks in a row make it "offline"; the
 * first answer after that makes it "online" again. `check` should be cheap (the health route).
 */
export function useServerReachable(check: () => Promise<unknown>): boolean {
  const [online, setOnline] = useState(true)
  const misses = useRef(0)
  const latest = useRef(check)
  useEffect(() => {
    latest.current = check
  })
  useEffect(() => {
    let alive = true
    const probe = async () => {
      try {
        await latest.current()
        misses.current = 0
        if (alive) setOnline(true)
      } catch {
        misses.current += 1
        if (alive && misses.current >= MISSES_BEFORE_OFFLINE) setOnline(false)
      }
    }
    const timer = window.setInterval(() => void probe(), CHECK_EVERY_MS)
    const lost = () => void probe()
    window.addEventListener('offline', lost)
    window.addEventListener('online', lost)
    return () => {
      alive = false
      window.clearInterval(timer)
      window.removeEventListener('offline', lost)
      window.removeEventListener('online', lost)
    }
  }, [])
  return online
}
