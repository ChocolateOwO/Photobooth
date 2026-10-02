import { useEffect, useRef } from 'react'

/** How often the booth checks whether anybody is still there. */
const IDLE_CHECK_MS = 1000
/**
 * Everything that means somebody is at the booth. Listened to in the capture phase, so a control
 * that stops an event (a sticker being dragged) still counts as somebody there (P9-R4).
 */
const ACTIVITY: (keyof WindowEventMap)[] = [
  'pointerdown',
  'pointermove',
  'pointerup',
  'keydown',
  'touchstart',
  'wheel',
]

function listen(handler: () => void): () => void {
  for (const name of ACTIVITY) {
    window.addEventListener(name, handler, { capture: true, passive: true })
  }
  return () => {
    for (const name of ACTIVITY) window.removeEventListener(name, handler, { capture: true })
  }
}

/**
 * While somebody is busy at the booth without it asking the server anything (decorating), tells
 * the server, at most every `everySeconds`, so their visit is not ended as abandoned under them.
 * The first touch after a quiet spell is told at once, not at the next tick (P9-R5). Nobody
 * touching the booth sends nothing: the visit may end as usual. No interval watches nothing.
 */
export function useKeepAlive(everySeconds: number | undefined, ping: () => void): void {
  const callback = useRef(ping)
  useEffect(() => {
    callback.current = ping
  })

  useEffect(() => {
    if (!everySeconds) return undefined
    const every = everySeconds * 1000
    let last = Date.now() // the screen has just read the visit
    let pending = false
    const send = () => {
      last = Date.now()
      pending = false
      callback.current()
    }
    const seen = () => {
      if (Date.now() - last >= every) send()
      else pending = true
    }
    const stop = listen(seen)
    const watch = window.setInterval(() => {
      if (pending && Date.now() - last >= every) send()
    }, IDLE_CHECK_MS)
    return () => {
      window.clearInterval(watch)
      stop()
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
    const stop = listen(() => {
      last = Date.now()
    })
    const watch = window.setInterval(() => {
      if (Date.now() - last < seconds * 1000) return
      window.clearInterval(watch) // once: the booth is going back to its start
      callback.current()
    }, IDLE_CHECK_MS)
    return () => {
      window.clearInterval(watch)
      stop()
    }
  }, [seconds])
}
