import { useEffect, useRef } from 'react'

/** How often the booth checks whether anybody is still there. */
const IDLE_CHECK_MS = 1000
const ACTIVITY: (keyof WindowEventMap)[] = ['pointerdown', 'keydown', 'touchstart', 'wheel']

/**
 * While somebody is busy at the booth without it asking the server anything (decorating), tells
 * the server now and then, at most every `everySeconds`, so their visit is not ended as
 * abandoned under them. Nobody touching the booth sends nothing: the visit may end as usual.
 */
export function useKeepAlive(everySeconds: number | undefined, ping: () => void): void {
  const callback = useRef(ping)
  useEffect(() => {
    callback.current = ping
  })

  useEffect(() => {
    if (!everySeconds) return undefined
    let busy = false
    const seen = () => {
      busy = true
    }
    for (const name of ACTIVITY) window.addEventListener(name, seen, { passive: true })
    const watch = window.setInterval(() => {
      if (!busy) return
      busy = false
      callback.current()
    }, everySeconds * 1000)
    return () => {
      window.clearInterval(watch)
      for (const name of ACTIVITY) window.removeEventListener(name, seen)
    }
  }, [everySeconds])
}

/**
 * Calls `onIdle` once nobody has touched the booth for `seconds` (the event's inactivity time).
 * No timeout (undefined or 0) watches nothing, e.g. while the finished photos are being made.
 */
export function useIdleTimeout(seconds: number | undefined, onIdle: () => void): void {
  const callback = useRef(onIdle)
  useEffect(() => {
    callback.current = onIdle
  })

  useEffect(() => {
    if (!seconds) return undefined
    let last = Date.now()
    const seen = () => {
      last = Date.now()
    }
    for (const name of ACTIVITY) window.addEventListener(name, seen, { passive: true })
    const watch = window.setInterval(() => {
      if (Date.now() - last < seconds * 1000) return
      window.clearInterval(watch) // once: the booth is going back to its start
      callback.current()
    }, IDLE_CHECK_MS)
    return () => {
      window.clearInterval(watch)
      for (const name of ACTIVITY) window.removeEventListener(name, seen)
    }
  }, [seconds])
}
