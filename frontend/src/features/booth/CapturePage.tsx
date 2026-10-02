import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'

import { ApiError, type BoothSessionState, type ShotState } from '../../shared/api/client'
import { useApiClient } from '../../shared/api/ApiClientContext'
import {
  CameraError,
  cameraMessage,
  chooseCamera,
  rememberedCamera,
  type CameraProblem,
  type CameraSource,
  type CameraView,
} from '../../shared/camera/camera'
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
import { CapturedPhotos } from './CapturedPhotos'
import { PhotoDialog } from './PhotoDialog'
import styles from './CapturePage.module.css'

/**
 * The photo session: one countdown and one photo per shot of the chosen frame.
 *
 * The server owns the truth (which photo is next, which attempt counts, when the set is
 * complete); this screen shows it and sends photos. The preview is mirrored when the event asks
 * for it, while the photo is stored exactly as the camera took it, so the mirror stays a setting
 * of the finished print rather than something baked into the original.
 */

type Phase = 'starting' | 'ready' | 'counting' | 'flash' | 'sending' | 'between' | 'complete'

const FLASH_MS = 220
const BETWEEN_SHOTS_MS = 900
/** How often the booth checks whether anybody is still there. */
const IDLE_CHECK_MS = 1000

interface PendingPhoto {
  shot: number
  attempt: number
  key: string
  photo: Blob
}

function newKey(): string {
  return crypto.randomUUID().replaceAll('-', '')
}

interface CapturePageProps {
  /** The booth camera. The real booth picks its own; tests hand in a stand-in. */
  camera?: CameraSource
}

export function CapturePage({ camera: given }: CapturePageProps = {}) {
  const api = useApiClient()
  const menu = useBoothMenu()
  const booth = useBoothServices()

  const [session, setSession] = useState<BoothSessionState | null>(null)
  const [phase, setPhase] = useState<Phase>('starting')
  const [count, setCount] = useState(0)
  const [busy, setBusy] = useState(false)
  // Set at once, before any re-render: two taps in the same frame can not both act (Phase 12).
  const acting = useRef(false)
  const [problem, setProblem] = useState<{ text: string; kind: CameraProblem | 'session' } | null>(
    null,
  )
  const videoRef = useRef<HTMLVideoElement>(null)
  const viewRef = useRef<CameraView | null>(null)
  const [live, setLive] = useState<CameraView | null>(null)
  // The camera is chosen once, on the Admin test page; the booth simply uses it.
  const [deviceId] = useState<string | null>(() => rememberedCamera())
  // The photo the review is showing large, and the one open in the dialog.
  const [picked, setPicked] = useState<number | null>(null)
  const [looking, setLooking] = useState<number | null>(null)
  const openerRef = useRef<HTMLElement | null>(null)
  const timers = useRef<number[]>([])
  // The photo waiting for its answer. A retry sends these very bytes again under the same key,
  // so a lost answer never turns into a second (different) photo (P67-002).
  const pending = useRef<PendingPhoto | null>(null)
  const camera = useMemo(() => given ?? chooseCamera(), [given])

  const clearTimers = useCallback(() => {
    for (const timer of timers.current) window.clearTimeout(timer)
    timers.current = []
  }, [])
  const later = useCallback((run: () => void, ms: number) => {
    timers.current.push(window.setTimeout(run, ms))
  }, [])
  const stopCamera = useCallback(() => {
    viewRef.current?.stop()
    viewRef.current = null
    setLive(null)
  }, [])
  // When somebody was last seen at the booth: a photo taken, or a touch, key or wheel.
  const activity = useRef(0)
  const seenSomebody = useCallback(() => {
    activity.current = Date.now()
  }, [])

  const next = useMemo(() => session?.shots.find((shot) => !shot.done) ?? null, [session])
  /** Where one shot's own photo lives; null while that shot has none (never another's). */
  const photoUrl = useCallback(
    (shot: ShotState) =>
      session && shot.capture_id
        ? api.captureImageUrl(session.id, shot.capture_id, shot.version ?? undefined)
        : null,
    [api, session],
  )
  const taken = session?.taken ?? 0
  const total = session?.expected_captures ?? 0
  const capturing = session?.state === 'capturing'

  // ---- the session ------------------------------------------------------------------------
  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const current = await api.currentSession()
        if (!alive) return
        if (!current || current.state === 'eligibility_ok') {
          booth.go('frames', { replace: true }) // no frame chosen yet
          return
        }
        if (current.state === 'reviewing') {
          booth.go('decorate', { replace: true }) // the photos are taken: decorating comes next
          return
        }
        if (current.state === 'delivered') {
          booth.go('done', { replace: true }) // the finished photos are made
          return
        }
        setSession(current)
        setPhase(current.state === 'capturing' ? 'ready' : 'complete')
      } catch {
        if (alive) booth.go('frames', { replace: true })
      }
    })()
    return () => {
      alive = false
    }
  }, [api, booth])

  // ---- the camera -------------------------------------------------------------------------
  // Bumped by "Try again" and by picking another camera: the effect opens it once per value.
  const [openings, setOpenings] = useState(0)
  const openCamera = useCallback(() => setOpenings((round) => round + 1), [])

  // The picture is attached when both the camera and the video element are there, whichever
  // arrives last (the screen shows "Loading…" until the visit is known).
  useEffect(() => {
    const video = videoRef.current
    if (!video || !live) return
    video.srcObject = live.stream
    try {
      void video.play()?.catch(() => undefined)
    } catch {
      // Some browsers (and jsdom) refuse to play; the stream still shows.
    }
  }, [live, session, problem, phase])

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const view = await camera.open(deviceId ?? undefined)
        if (!alive) {
          view.stop()
          return
        }
        viewRef.current?.stop() // never leave the previous camera running
        viewRef.current = view
        setLive(view)
        setProblem(null)
      } catch (error) {
        if (!alive) return
        const trouble = error instanceof CameraError ? error.problem : 'failed'
        setProblem({ text: cameraMessage(trouble), kind: trouble })
        // Ready to try again as soon as a camera answers (P67-003).
        setPhase((current) => (current === 'complete' ? current : 'ready'))
      }
    })()
    return () => {
      alive = false
    }
  }, [camera, deviceId, openings])

  useEffect(
    () => () => {
      viewRef.current?.stop()
      viewRef.current = null
    },
    [],
  )

  useEffect(() => () => clearTimers(), [clearTimers])

  // ---- taking one photo --------------------------------------------------------------------
  const sendPhoto = useCallback(async () => {
    const view = viewRef.current
    const shot = next
    if (!session || !shot) return
    let waiting = pending.current
    if (waiting && (waiting.shot !== shot.shot_index || waiting.attempt !== shot.attempt_no)) {
      waiting = null // it belonged to a photo the session has moved past
      pending.current = null
    }
    if (!waiting) {
      if (!view || !view.live()) {
        setProblem({ text: cameraMessage('lost'), kind: 'lost' })
        setPhase('ready')
        return
      }
      setPhase('flash')
      try {
        waiting = {
          shot: shot.shot_index,
          attempt: shot.attempt_no,
          key: newKey(),
          photo: await view.photo(),
        }
      } catch (error) {
        const trouble = error instanceof CameraError ? error.problem : 'failed'
        setProblem({ text: cameraMessage(trouble), kind: trouble })
        setPhase('ready')
        return
      }
      pending.current = waiting
    }
    setPhase('sending')
    try {
      const result = await api.sendCapture(session.id, waiting.photo, {
        index: waiting.shot,
        attempt: waiting.attempt,
        idempotencyKey: waiting.key,
      })
      pending.current = null
      seenSomebody() // a photo was taken: somebody is still at the booth
      setSession(result.session)
      if (result.session.taken >= result.session.expected_captures) {
        setPhase('complete')
      } else {
        setPhase('between')
        later(() => setPhase('ready'), BETWEEN_SHOTS_MS)
      }
    } catch (error) {
      if (error instanceof ApiError && (error.status === 409 || error.status === 422)) {
        // The visit moved on (a retake, a timeout, another photo): the participant did nothing
        // wrong, so the booth follows the server and simply carries on with the next photo.
        pending.current = null
        try {
          const fresh = await api.readSession(session.id)
          setSession(fresh)
          setPhase(fresh.state === 'capturing' ? 'ready' : 'complete')
          return
        } catch {
          booth.go('frames', { replace: true })
          return
        }
      }
      setProblem({ text: 'That photo did not reach the booth. Try again.', kind: 'session' })
      setPhase('ready')
    }
  }, [api, later, booth, next, seenSomebody, session])

  // ---- the countdown -----------------------------------------------------------------------
  const startCountdown = useCallback(() => {
    // Never count down towards a photo the camera can not take.
    if (!session || !next || problem || !live?.live()) return
    clearTimers()
    const seconds = session.countdown_seconds
    setCount(seconds)
    setPhase('counting')
    for (let left = seconds - 1; left >= 0; left--) {
      later(() => setCount(left), (seconds - left) * 1000)
    }
    later(() => {
      void sendPhoto()
      later(() => undefined, FLASH_MS)
    }, seconds * 1000)
  }, [clearTimers, later, live, next, problem, sendPhoto, session])

  // The next photo starts by itself once the booth is ready for it.
  useEffect(() => {
    if (phase !== 'ready' || problem || !next || !live) return
    const start = window.setTimeout(() => startCountdown(), 400)
    return () => window.clearTimeout(start)
  }, [live, next, phase, problem, startCountdown])

  // A camera that stops while the booth waits (unplugged, or refused) stops the countdown too;
  // the number itself is only on screen while a countdown is running.
  useEffect(() => {
    if (problem) clearTimers()
  }, [clearTimers, problem])

  // The booth watches the camera even between photos, so an unplugged one is noticed at once
  // instead of leaving the screen counting down towards a picture that can not be taken.
  useEffect(() => {
    if (!live || problem) return undefined
    const watch = window.setInterval(() => {
      if (!live.live()) {
        setProblem({ text: cameraMessage('lost'), kind: 'lost' })
        setPhase((current) => (current === 'complete' ? current : 'ready'))
      }
    }, 700)
    return () => window.clearInterval(watch)
  }, [live, problem])

  // ---- what the participant can do ---------------------------------------------------------
  const leave = useCallback(
    async (reason: 'gave-up' | 'timed-out') => {
      clearTimers()
      stopCamera()
      pending.current = null
      const current = session
      if (current && current.state === 'capturing') {
        try {
          await api.giveUpSession(current.id)
        } catch {
          // Leaving always works for the participant; the visit also ends by itself.
        }
      }
      booth.go('start', { replace: reason === 'timed-out' })
    },
    [api, booth, clearTimers, session, stopCamera],
  )

  // Nobody at the booth for the event's inactivity time: the visit ends and the booth goes back
  // to its start screen, camera off, ready for the next guest (P67-004).
  useEffect(() => {
    const timeout = session?.inactivity_timeout_s
    if (!timeout || !session) return undefined
    const events: (keyof WindowEventMap)[] = ['pointerdown', 'keydown', 'touchstart', 'wheel']
    for (const name of events) window.addEventListener(name, seenSomebody, { passive: true })
    const watch = window.setInterval(() => {
      if (!activity.current) seenSomebody() // the clock starts when this screen does
      else if (Date.now() - activity.current >= timeout * 1000) void leave('timed-out')
    }, IDLE_CHECK_MS)
    return () => {
      window.clearInterval(watch)
      for (const name of events) window.removeEventListener(name, seenSomebody)
    }
  }, [leave, seenSomebody, session])

  const retake = async (shotIndex?: number) => {
    if (!session || busy || acting.current) return
    acting.current = true
    clearTimers()
    setBusy(true)
    pending.current = null
    try {
      // The version says which state of the visit this answers, so a second tap that arrives
      // after a new photo can not throw that photo away (P67-006).
      const updated = await api.retakeCapture(session.id, shotIndex, session.state_version)
      setSession(updated)
      setPhase('ready')
    } catch {
      setProblem({ text: 'That photo could not be taken again.', kind: 'session' })
    } finally {
      acting.current = false
      setBusy(false)
    }
  }

  const finish = async () => {
    if (!session || busy || acting.current) return
    acting.current = true
    setBusy(true)
    try {
      await api.finishCaptures(session.id)
      clearTimers()
      stopCamera() // the camera light goes out as soon as the photos are done
      booth.go('decorate') // decorating, then the finished photos and the take-home link
    } catch {
      setProblem({ text: 'The booth could not finish the session.', kind: 'session' })
    } finally {
      acting.current = false
      setBusy(false)
    }
  }

  if (menu.isPending || !session) {
    return (
      <BoothShell>
        <p className={styles.plain}>Loading…</p>
      </BoothShell>
    )
  }

  const tokens = menu.isSuccess ? menu.data.theme : {}
  const complete = session.taken >= session.expected_captures
  const frame = menu.isSuccess
    ? (menu.data.frames.find((one) => one.id === session.frame_id) ?? null)
    : null
  const frameName = frame?.name ?? null
  // The camera is shown in the shape of one photo of this frame, so what the participant sees is
  // what the print keeps. The shape comes from the template itself, never from a guess here.
  const slot = frame?.plan.photo_slot ?? null
  const shape = slot
    ? ({ '--pb-slot-w': String(slot.width), '--pb-slot-h': String(slot.height) } as CSSProperties)
    : undefined
  const canRetakeOne = capturing && session.retake_mode === 'per_photo'
  const canRetakeAll = capturing && session.retake_mode === 'all'

  // The review shows one photo big; until somebody picks another it is the first one taken.
  const withPhoto = session.shots.filter((shot) => photoUrl(shot) !== null)
  const shown = withPhoto.find((shot) => shot.shot_index === picked) ?? withPhoto[0] ?? null
  const shownUrl = shown ? photoUrl(shown) : null
  const open = session.shots.find((shot) => shot.shot_index === looking) ?? null
  const openUrl = open ? photoUrl(open) : null

  const pick = (shot: ShotState, opener: HTMLButtonElement) => {
    if (complete) {
      setPicked(shot.shot_index) // the big picture follows the place that was pressed
      return
    }
    openerRef.current = opener
    setLooking(shot.shot_index)
  }

  return (
    <BoothShell>
      <EventScreen tokens={tokens} className={styles.screen} label="Photo session">
        <div className={styles.header}>
          <EventHeading level={1}>
            {complete ? 'All photos taken' : 'Look at the camera'}
          </EventHeading>
          <p className={styles.progress} data-testid="capture-progress" role="status">
            {complete
              ? `${session.taken} of ${total} photos`
              : `Photo ${Math.min(taken + 1, total)} of ${total}`}
          </p>
        </div>

        <div className={styles.stage}>
          {/* One photo's shape, as large as this screen allows: the camera while the photos are
              being taken, and the chosen photo itself once they are all there. */}
          <div className={styles.frame} style={shape} data-testid="photo-frame">
            {complete && shownUrl && shown ? (
              <button
                type="button"
                className={styles.bigButton}
                aria-label={`Photo ${shown.shot_index}, see it bigger`}
                onClick={(event) => {
                  openerRef.current = event.currentTarget
                  setLooking(shown.shot_index)
                }}
              >
                <img
                  src={shownUrl}
                  alt={`Photo ${shown.shot_index}`}
                  className={styles.big}
                  data-mirrored={session.mirror ? '' : undefined}
                  data-testid="review-photo"
                />
              </button>
            ) : (
              <video
                ref={videoRef}
                className={styles.preview}
                data-mirrored={session.mirror ? '' : undefined}
                playsInline
                muted
                autoPlay
                aria-label="Camera preview"
              />
            )}
            {phase === 'counting' && (
              <p className={styles.countdown} data-testid="countdown" aria-live="assertive">
                {count > 0 ? count : 'Smile!'}
              </p>
            )}
            {phase === 'flash' && (
              <div className={styles.flash} data-testid="flash" aria-hidden="true" />
            )}
            {phase === 'sending' && (
              <p className={styles.working} role="status">
                Keeping that one…
              </p>
            )}
            {problem && (
              <div className={styles.problem} role="alert">
                <EventMessage kind="error">{problem.text}</EventMessage>
                <div className={styles.problemActions}>
                  <EventButton
                    variant="primary"
                    onClick={() => {
                      if (problem.kind === 'session') {
                        setProblem(null)
                        setPhase('ready')
                      } else {
                        openCamera() // opens it again, and clears this message when it works
                      }
                    }}
                  >
                    Try again
                  </EventButton>
                  <EventButton variant="secondary" onClick={() => void leave('gave-up')}>
                    Start over
                  </EventButton>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Every shot has its place here, in order: a photo only ever appears under its own
            number. Pressing one opens it large, or chooses it on the review screen. */}
        <CapturedPhotos
          shots={session.shots}
          photoUrl={photoUrl}
          onPick={pick}
          mirror={session.mirror}
          select={complete}
          {...(shown ? { selected: shown.shot_index } : {})}
        />

        <div className={styles.actions}>
          {complete ? (
            <>
              <EventText>
                {frameName && session.layout_label
                  ? `${frameName} · ${session.layout_label} · ${session.taken} photos`
                  : `${session.taken} photos`}
              </EventText>
              <EventText>
                {capturing ? 'Happy with these?' : 'The photos are ready for the next step.'}
              </EventText>
              {canRetakeAll && (
                <EventButton variant="secondary" disabled={busy} onClick={() => void retake()}>
                  Take all the photos again
                </EventButton>
              )}
              {canRetakeOne && (
                <div className={styles.retakes} role="group" aria-label="Take one photo again">
                  {session.shots.map((shot) => (
                    <EventButton
                      key={shot.shot_index}
                      variant="secondary"
                      disabled={busy}
                      onClick={() => void retake(shot.shot_index)}
                    >
                      Photo {shot.shot_index} again
                    </EventButton>
                  ))}
                </div>
              )}
              {capturing ? (
                <EventButton variant="primary" disabled={busy} onClick={() => void finish()}>
                  These are good
                </EventButton>
              ) : (
                <EventButton variant="primary" onClick={() => void leave('gave-up')}>
                  Back to the start
                </EventButton>
              )}
            </>
          ) : (
            <EventButton variant="secondary" onClick={() => void leave('gave-up')}>
              Stop and start over
            </EventButton>
          )}
        </div>

        {open && openUrl && (
          <PhotoDialog
            shotIndex={open.shot_index}
            url={openUrl}
            mirror={session.mirror}
            busy={busy}
            onClose={() => {
              setLooking(null)
              openerRef.current?.focus()
            }}
            {...(canRetakeOne
              ? {
                  onRetake: () => {
                    const shot = open.shot_index
                    setLooking(null)
                    openerRef.current?.focus()
                    void retake(shot)
                  },
                }
              : {})}
          />
        )}
      </EventScreen>
    </BoothShell>
  )
}
