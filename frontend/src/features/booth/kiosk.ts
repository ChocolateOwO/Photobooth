import { useEffect, useRef, useState } from 'react'

/**
 * Kiosk behaviour for the booth's own display.
 *
 * A touchscreen kiosk gets every kind of accidental input: double taps, a palm resting on the
 * screen, a long press that opens a menu, a pinch that zooms the page, a stray Escape that leaves
 * fullscreen. And its server may stop answering for a moment. These helpers keep the booth usable
 * through all of them.
 */

/**
 * Settles when `work` settles or when `ms` have passed, whichever comes first, and never
 * rejects; whatever `work` does later is ignored. For actions that must not hang the booth on a
 * server that accepts a request but never answers it (P12-R1).
 */
export function settleWithin(work: Promise<unknown>, ms: number): Promise<'done' | 'late'> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve('late'), ms)
    const done = () => {
      window.clearTimeout(timer)
      resolve('done')
    }
    work.then(done, done)
  })
}

/** How long leaving a visit waits for the server before going to the start anyway. */
export const LEAVE_DEADLINE_MS = 4000

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
 * Whether this pointer event lets the page ask for fullscreen. Browsers grant it only on an
 * activation-triggering event: pressing a mouse button, but lifting a finger or a pen (HTML
 * "activation triggering input event"); asking on a finger's touch-down is refused (P12-R3).
 */
export function grantsActivation(event: Event): boolean {
  const pointer = (event as PointerEvent).pointerType ?? ''
  if (event.type === 'pointerdown') return pointer === 'mouse'
  if (event.type === 'pointerup') return pointer !== 'mouse'
  return false
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
    const touched = (event: Event) => {
      if (fullscreen && grantsActivation(event)) enterFullscreen()
    }
    document.addEventListener('contextmenu', refuse)
    document.addEventListener('dragstart', refuse)
    document.addEventListener('pointerdown', touched, { capture: true })
    document.addEventListener('pointerup', touched, { capture: true })
    return () => {
      if (viewport && before !== null) viewport.setAttribute('content', before)
      document.removeEventListener('contextmenu', refuse)
      document.removeEventListener('dragstart', refuse)
      document.removeEventListener('pointerdown', touched, { capture: true })
      document.removeEventListener('pointerup', touched, { capture: true })
    }
  }, [fullscreen])
}

/** How often the booth checks it can still reach its server, and after how many misses. */
const CHECK_EVERY_MS = 5000
const MISSES_BEFORE_OFFLINE = 2
/** A check not answered within this time is a miss (a server that accepts but never answers). */
export const CHECK_DEADLINE_MS = 4000

/**
 * Whether the booth can reach its server. Two missed checks in a row make it "offline"; the
 * first healthy answer after that makes it "online" again. A check not answered within its
 * deadline is a miss, and a new check never starts while one is still out, so a late answer can
 * not override a newer one (P12-R2). `check` should be cheap (the health route).
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
    let checking = false
    const probe = async () => {
      if (checking) return
      checking = true
      // Neither promise can fail: an error answer is simply not a healthy one.
      const answer = latest.current().then(
        () => true,
        () => false,
      )
      const healthy = (await settleWithin(answer, CHECK_DEADLINE_MS)) === 'done' && (await answer)
      checking = false
      if (!alive) return
      if (healthy) {
        misses.current = 0
        setOnline(true)
      } else {
        misses.current += 1
        if (misses.current >= MISSES_BEFORE_OFFLINE) setOnline(false)
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
