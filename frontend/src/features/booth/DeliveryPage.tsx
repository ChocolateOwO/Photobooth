import { useCallback, useEffect, useRef, useState } from 'react'

import { type BoothSessionState, type DeliveryLink } from '../../shared/api/client'
import { useApiClient } from '../../shared/api/ApiClientContext'
import {
  EventButton,
  EventHeading,
  EventMessage,
  EventScreen,
  EventText,
} from '../../shared/eventUi/EventUi'
import { BoothShell } from './BoothShell'
import { useBoothMenu } from './boothMenu'
import { useBoothServices } from './boothServices'
import styles from './DeliveryPage.module.css'

/**
 * The end of a visit: the finished photos and the QR code that takes them home.
 *
 * The finished photos were made when the guest confirmed their decorations; this screen shows them
 * next to the take-home link. The link lives only on this screen and in the guest's phone; the booth
 * never stores it. When the guest is done, or walks away, the booth goes back to its start.
 */

/** How often the booth checks whether anybody is still there. */
const IDLE_CHECK_MS = 1000

function until(iso: string): string {
  const moment = new Date(iso)
  // The booth speaks English everywhere, whatever language the machine is set to.
  return moment.toLocaleString('en-GB', {
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
  })
}

type Stage = 'loading' | 'ready' | 'failed'

export function DeliveryPage() {
  const api = useApiClient()
  const menu = useBoothMenu()
  const booth = useBoothServices()
  const [session, setSession] = useState<BoothSessionState | null>(null)
  const [link, setLink] = useState<DeliveryLink | null>(null)
  const [stage, setStage] = useState<Stage>('loading')
  const [problem, setProblem] = useState<string | null>(null)
  const [leaving, setLeaving] = useState(false)
  const leavingNow = useRef(false)
  const activity = useRef(0)

  // ---- the visit, then its link --------------------------------------------------------
  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const current = await api.currentSession()
        if (!alive) return
        if (!current) {
          booth.go('start', { replace: true })
          return
        }
        if (current.state === 'eligibility_ok') {
          booth.go('frames', { replace: true })
          return
        }
        if (current.state === 'capturing') {
          booth.go('capture', { replace: true })
          return
        }
        if (current.state === 'reviewing') {
          // The finished photos are not made yet: the guest is still choosing decorations.
          booth.go('decorate', { replace: true })
          return
        }
        // Known from here on: whatever happens next, the booth can close this visit and its
        // inactivity time still sends the booth back to the start.
        setSession(current)
        const issued = await api.deliveryLink(current.id)
        if (!alive) return
        setLink(issued)
        setStage('ready')
      } catch {
        if (!alive) return
        setStage('failed')
        setProblem('Sorry, your photos could not be shown. Please start over.')
      }
    })()
    return () => {
      alive = false
    }
  }, [api, booth])

  // ---- leaving --------------------------------------------------------------------------
  const leave = useCallback(
    async (replace: boolean) => {
      if (leaving || leavingNow.current) return
      leavingNow.current = true // at once: a double tap on Done leaves once (Phase 12)
      setLeaving(true)
      if (session) {
        try {
          await api.giveUpSession(session.id) // a delivered visit simply completes
        } catch {
          // Leaving always works for the guest; the visit also ends by itself.
        }
      }
      booth.go('start', { replace })
    },
    [api, booth, leaving, session],
  )

  // Nobody at the booth for the event's inactivity time: back to the start for the next guest.
  const seenSomebody = useCallback(() => {
    activity.current = Date.now()
  }, [])
  useEffect(() => {
    const timeout = session?.inactivity_timeout_s
    if (!timeout) return undefined
    const events: (keyof WindowEventMap)[] = ['pointerdown', 'keydown', 'touchstart', 'wheel']
    for (const name of events) window.addEventListener(name, seenSomebody, { passive: true })
    const watch = window.setInterval(() => {
      if (!activity.current) seenSomebody()
      else if (Date.now() - activity.current >= timeout * 1000) void leave(true)
    }, IDLE_CHECK_MS)
    return () => {
      window.clearInterval(watch)
      for (const name of events) window.removeEventListener(name, seenSomebody)
    }
  }, [leave, seenSomebody, session])

  const tokens = menu.isSuccess ? menu.data.theme : {}
  const outputs = session?.outputs ?? []

  return (
    <BoothShell>
      <EventScreen tokens={tokens} className={styles.screen} label="Your photos">
        {stage === 'loading' && (
          <div className={styles.making} role="status" data-testid="loading-photos">
            <span className={styles.spinner} aria-hidden="true" />
            <EventHeading level={1}>Getting your photos…</EventHeading>
          </div>
        )}

        {stage === 'failed' && (
          <div className={styles.making} role="alert">
            <EventMessage kind="error">{problem}</EventMessage>
            <EventButton variant="primary" onClick={() => void leave(false)}>
              Start over
            </EventButton>
          </div>
        )}

        {stage === 'ready' && session && link && (
          <>
            <div className={styles.header}>
              <EventHeading level={1}>Your photos are ready!</EventHeading>
            </div>
            <div className={styles.body}>
              <ul
                className={styles.outputs}
                data-count={outputs.length}
                aria-label="Your finished photos"
                data-testid="finished-photos"
              >
                {outputs.map((output) => (
                  <li key={output.id} className={styles.output}>
                    <img
                      src={api.outputImageUrl(session.id, output.id, output.version)}
                      alt={
                        outputs.length === 1
                          ? 'Your finished photo'
                          : `Finished photo ${output.output_index} of ${outputs.length}`
                      }
                      width={output.width}
                      height={output.height}
                      className={styles.photo}
                    />
                  </li>
                ))}
              </ul>

              <section className={styles.take} aria-labelledby="take-home">
                <h2 id="take-home" className={styles.takeTitle}>
                  Scan to take them home
                </h2>
                <img
                  className={styles.qr}
                  src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(link.qr_svg)}`}
                  alt="QR code that opens your photos"
                  data-testid="delivery-qr"
                />
                <EventText>
                  Point your phone camera at the code. Your phone must be on the same Wi-Fi as
                  the booth.
                </EventText>
                <p className={styles.url} data-testid="delivery-url">
                  {link.url}
                </p>
                <EventText muted>The link works until {until(link.expires_at)}.</EventText>
              </section>
            </div>
            <div className={styles.actions}>
              <EventButton
                variant="primary"
                disabled={leaving}
                onClick={() => void leave(false)}
              >
                Done
              </EventButton>
            </div>
          </>
        )}
      </EventScreen>
    </BoothShell>
  )
}
