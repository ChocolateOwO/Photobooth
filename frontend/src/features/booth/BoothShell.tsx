import { useEffect, useRef, type ReactNode } from 'react'

import { useApiClient } from '../../shared/api/ApiClientContext'
import { useEnterImmersive } from '../../shared/ui/immersive'
import { Reconnecting } from './BoothSafety'
import { useBoothServices } from './boothServices'
import { useKioskMode, useServerReachable } from './kiosk'
import styles from './BoothShell.module.css'

/**
 * The booth's own display.
 *
 * Every participant screen sits in this one shell, whether a guest opened `/booth` or an
 * organizer started a test from Admin: it takes the whole viewport (the whole display when the
 * browser grants fullscreen), keeps the page from scrolling, respects the device's safe areas,
 * and puts nothing of the surrounding app on screen. There is no second booth layout.
 *
 * It is also where the booth behaves as a kiosk: no zoom, long-press menus or dragging, the real
 * booth asks for fullscreen again on the next touch after it was left (an organizer's test does
 * not), and when the booth's own server stops answering the screen says so and waits, rather
 * than half-working underneath.
 */
export function BoothShell({ children }: { children: ReactNode }) {
  useEnterImmersive()
  const api = useApiClient()
  const booth = useBoothServices()
  useKioskMode(!booth.isTest)
  // Any check that is not a healthy answer in time is a miss: no answer at all, a proxy in front
  // of a stopped server (it answers 502), or a server whose database does not answer (503).
  const online = useServerReachable(api.health)

  // While the cover is up, the screen under it stays mounted (the visit, the camera, a photo
  // waiting to be sent) but takes no input at all, not even a key on a focused button; focus
  // goes back where it was once the server answers again (P12-R5).
  // (The browser drops focus from a subtree the moment it turns inert, so the last focus inside
  // the screen is remembered as it happens.)
  const lastFocus = useRef<HTMLElement | null>(null)
  const cover = useRef<HTMLDivElement | null>(null)
  const wasOnline = useRef(true)
  useEffect(() => {
    if (online === wasOnline.current) return
    wasOnline.current = online
    if (!online) {
      cover.current?.focus()
    } else if (lastFocus.current?.isConnected) {
      lastFocus.current.focus()
    }
  }, [online])

  return (
    <div className={styles.shell} data-testid="booth-shell">
      <div
        className={styles.screen}
        inert={!online}
        data-testid="booth-screen"
        onFocus={(event) => {
          if (event.target instanceof HTMLElement) lastFocus.current = event.target
        }}
      >
        {children}
      </div>
      {!online && <Reconnecting ref={cover} />}
    </div>
  )
}
