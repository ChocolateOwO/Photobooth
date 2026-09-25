import { useEffect, useRef, useState } from 'react'

import type { FramePlan } from '../../shared/api/client'
import { useApiClient } from '../../shared/api/ApiClientContext'
import { EventButton, EventMessage, EventScreen, EventText } from '../../shared/eventUi/EventUi'
import { FrameCarousel } from '../../shared/eventUi/FrameCarousel'
import { planSummary, type GalleryFrame } from '../../shared/eventUi/framePlan'
import { BoothLoadState } from './BoothLoadState'
import { useBoothMenu } from './boothMenu'
import styles from './FrameSelectPage.module.css'

/** Where the confirmed frame waits for the capture step of the session (a later phase). */
export const SESSION_FRAME_KEY = 'pb.booth.chosenFrame'

function remembered(): FramePlan | null {
  try {
    const stored = sessionStorage.getItem(SESSION_FRAME_KEY)
    return stored ? (JSON.parse(stored) as FramePlan) : null
  } catch {
    return null
  }
}

function remember(plan: FramePlan | null): void {
  try {
    if (plan) sessionStorage.setItem(SESSION_FRAME_KEY, JSON.stringify(plan))
    else sessionStorage.removeItem(SESSION_FRAME_KEY)
  } catch {
    // Storage may be unavailable (private mode); the choice stays in this screen's state.
  }
}

/** Participant screen: choose the frame, confirm it, then start (capture comes next phase). */
export function FrameSelectPage() {
  const api = useApiClient()
  const menu = useBoothMenu()
  const [plan, setPlan] = useState<FramePlan | null>(null)
  // Coming back to this screen (or choosing again) opens the carousel on the last chosen frame.
  const [lastChosen, setLastChosen] = useState<string | null>(() => remembered()?.frame_id ?? null)
  const [started, setStarted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  // Each confirmation is numbered; Back, Start, choosing again or leaving the screen make any
  // answer still on its way obsolete, so a late answer never replaces a newer choice.
  const confirmation = useRef(0)
  const forgetPending = () => {
    confirmation.current += 1
    setBusy(false)
  }
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
  const chosen = plan ? frames.find((f) => f.id === plan.frame_id) : undefined

  return (
    <EventScreen tokens={menu.data.theme} className={styles.screen} label="Frame selection">
      {frames.length === 0 ? (
        <EventMessage kind="info">No frames are available for this event.</EventMessage>
      ) : started && chosen && plan ? (
        <div className={styles.ready} role="status">
          <EventText>
            Ready: {chosen.name} ({planSummary(chosen.plan)}). The camera starts in the next step.
          </EventText>
          <EventButton
            variant="secondary"
            onClick={() => {
              setStarted(false)
              setPlan(null)
              remember(null)
            }}
          >
            Choose a different frame
          </EventButton>
        </div>
      ) : (
        <FrameCarousel
          frames={frames}
          allowSurprise={menu.data.allow_surprise_me}
          selectedId={plan?.frame_id ?? null}
          startAtId={plan?.frame_id ?? lastChosen}
          busy={busy}
          onConfirm={async (frame) => {
            confirmation.current += 1
            const mine = confirmation.current
            setBusy(true)
            setProblem(null)
            try {
              const confirmed = await api.chooseFrame(frame.id)
              if (confirmation.current !== mine) return // superseded meanwhile
              setPlan(confirmed)
              setLastChosen(confirmed.frame_id)
              remember(confirmed)
            } catch {
              if (confirmation.current !== mine) return
              setProblem('That frame could not be chosen. Please pick again.')
              void menu.refetch()
            } finally {
              if (confirmation.current === mine) setBusy(false)
            }
          }}
          onCancel={forgetPending}
          onStart={() => {
            forgetPending()
            setStarted(true)
          }}
          onChooseAgain={() => {
            forgetPending()
            setPlan(null)
            remember(null)
          }}
        />
      )}
      {problem && <EventMessage kind="error">{problem}</EventMessage>}
    </EventScreen>
  )
}
