import { useEffect, useSyncExternalStore } from 'react'

/**
 * Immersive mode: while a booth screen is on, nothing of the surrounding app is on screen.
 *
 * The booth is the same screen whether a guest opens `/booth` or an organizer runs it from
 * Admin, so it takes the whole display in both cases: the Admin header, the navigation, the
 * "Signed in as" line, the Dummy badge and the page's own scrolling all step aside until the
 * booth is left again. Nested booth screens are counted, so leaving one of them does not undo
 * the mode while another is still on.
 */

export const IMMERSIVE_ATTRIBUTE = 'data-booth-immersive'

let depth = 0
const listeners = new Set<() => void>()

function announce(): void {
  for (const listener of [...listeners]) listener()
}

/** Turn immersive mode on; the returned function turns this caller's share of it off again. */
export function enterImmersive(): () => void {
  depth += 1
  document.documentElement.setAttribute(IMMERSIVE_ATTRIBUTE, '')
  announce()
  let left = false
  return () => {
    if (left) return
    left = true
    depth = Math.max(0, depth - 1)
    if (depth === 0) document.documentElement.removeAttribute(IMMERSIVE_ATTRIBUTE)
    announce()
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function immersiveNow(): boolean {
  return depth > 0
}

/** True while any booth screen is on. Server rendering has no booth, so it is false there. */
export function useImmersive(): boolean {
  return useSyncExternalStore(subscribe, immersiveNow, () => false)
}

/** Keeps immersive mode on for as long as the calling component is mounted. */
export function useEnterImmersive(): void {
  useEffect(() => enterImmersive(), [])
}
