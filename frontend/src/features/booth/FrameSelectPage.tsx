import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'

import { useApiClient } from '../../shared/api/ApiClientContext'
import { EventMessage, EventScreen } from '../../shared/eventUi/EventUi'
import { FrameCarousel } from '../../shared/eventUi/FrameCarousel'
import { type GalleryFrame } from '../../shared/eventUi/framePlan'
import { BoothLoadState } from './BoothLoadState'
import { useBoothMenu } from './boothMenu'
import styles from './FrameSelectPage.module.css'

/** The frame this browser confirmed, so coming back opens the carousel where it was left. */
export const SESSION_FRAME_KEY = 'pb.booth.chosenFrame'

function remembered(): string | null {
  try {
    return sessionStorage.getItem(SESSION_FRAME_KEY)
  } catch {
    return null
  }
}

function remember(frameId: string | null): void {
  try {
    if (frameId) sessionStorage.setItem(SESSION_FRAME_KEY, frameId)
    else sessionStorage.removeItem(SESSION_FRAME_KEY)
  } catch {
    // Storage may be unavailable (private mode); the choice stays in this screen's state.
  }
}

function newKey(): string {
  return crypto.randomUUID().replaceAll('-', '')
}

/** Participant screen: choose the frame, confirm it, and the photo session begins. */
export function FrameSelectPage() {
  const api = useApiClient()
  const menu = useBoothMenu()
  const navigate = useNavigate()
  const [lastChosen, setLastChosen] = useState<string | null>(() => remembered())
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  // Each confirmation is numbered; leaving the screen makes an answer still on its way obsolete.
  const confirmation = useRef(0)
  // One key per visit start: a retry after a lost answer joins the same visit, never a second one.
  const startKey = useRef(newKey())
  useEffect(() => () => {
    confirmation.current += 1
  }, [])

  if (menu.isPending) {
    return <p className={styles.plain}>Loading…</p>
  }
  if (menu.isError) {
    return <BoothLoadState error={menu.error} onRetry={() => void menu.refetch()} />
  }

  const frames: GalleryFrame[] = menu.data.frames.map((frame) => ({
    id: frame.id,
    name: frame.name,
    previewUrl: frame.preview_url,
    plan: frame.plan,
  }))

  return (
    <EventScreen tokens={menu.data.theme} className={styles.screen} label="Frame selection">
      {frames.length === 0 ? (
        <EventMessage kind="info">No frames are available for this event.</EventMessage>
      ) : (
        <FrameCarousel
          frames={frames}
          allowSurprise={menu.data.allow_surprise_me}
          startAtId={lastChosen}
          busy={busy}
          // Only "Start with this frame" in the pop-up gets here: the visit begins, the frame is
          // pinned to it (with its photo count) and the camera step opens. Until then nothing is
          // chosen and nothing is stored.
          onStart={async (frame) => {
            confirmation.current += 1
            const mine = confirmation.current
            setBusy(true)
            setProblem(null)
            try {
              const session = await api.startSession(startKey.current)
              const capturing = await api.chooseSessionFrame(session.id, frame.id)
              if (confirmation.current !== mine) return // superseded meanwhile
              setLastChosen(frame.id)
              remember(frame.id)
              navigate('/booth/capture', { state: { session: capturing.id } })
            } catch {
              if (confirmation.current !== mine) return
              setProblem('That frame could not be chosen. Please pick again.')
              startKey.current = newKey() // the next try starts its own visit
              void menu.refetch()
            } finally {
              if (confirmation.current === mine) setBusy(false)
            }
          }}
        />
      )}
      {problem && <EventMessage kind="error">{problem}</EventMessage>}
    </EventScreen>
  )
}
