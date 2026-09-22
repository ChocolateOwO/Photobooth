import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { ApiError, type FramePlan } from '../../shared/api/client'
import { useApiClient } from '../../shared/api/ApiClientContext'
import { EventButton, EventMessage, EventScreen, EventText } from '../../shared/eventUi/EventUi'
import { FrameGallery } from '../../shared/eventUi/FrameGallery'
import { planSummary, type GalleryFrame } from '../../shared/eventUi/framePlan'
import styles from './FrameSelectPage.module.css'

/** Where the confirmed frame waits for the capture step of the session (a later phase). */
export const SESSION_FRAME_KEY = 'pb.booth.chosenFrame'

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
  const menu = useQuery({ queryKey: ['booth', 'frames'], queryFn: () => api.frameMenu(), retry: false })
  const [plan, setPlan] = useState<FramePlan | null>(null)
  const [started, setStarted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  if (menu.isPending) {
    return <p className={styles.plain}>Loading…</p>
  }
  if (menu.isError) {
    const noEvent = menu.error instanceof ApiError && menu.error.status === 404
    const notPaired = menu.error instanceof ApiError && menu.error.status === 401
    return (
      <div className={styles.plain} role="alert">
        <p>
          {noEvent
            ? 'This booth has no active event yet. Ask the organizer to activate an Event Profile.'
            : notPaired
              ? 'This screen is not paired with the booth.'
              : 'The frames could not be loaded.'}
        </p>
        <button type="button" className={styles.retry} onClick={() => void menu.refetch()}>
          Try again
        </button>
      </div>
    )
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
        <FrameGallery
          frames={frames}
          allowSurprise={menu.data.allow_surprise_me}
          selectedId={plan?.frame_id ?? null}
          busy={busy}
          onConfirm={async (frame) => {
            setBusy(true)
            setProblem(null)
            try {
              const confirmed = await api.chooseFrame(frame.id)
              setPlan(confirmed)
              remember(confirmed)
            } catch {
              setProblem('That frame could not be chosen. Please pick again.')
              void menu.refetch()
            } finally {
              setBusy(false)
            }
          }}
          onStart={() => setStarted(true)}
          onChooseAgain={() => {
            setPlan(null)
            remember(null)
          }}
        />
      )}
      {problem && <EventMessage kind="error">{problem}</EventMessage>}
    </EventScreen>
  )
}
