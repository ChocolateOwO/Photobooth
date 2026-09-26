import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'

import { ApiError, type BoothSessionState } from '../../shared/api/client'
import { useApiClient } from '../../shared/api/ApiClientContext'
import {
  CameraError,
  cameraMessage,
  chooseCamera,
  rememberCamera,
  rememberedCamera,
  type CameraDevice,
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
import { useBoothMenu } from './boothMenu'
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
  const navigate = useNavigate()
  const instance = (import.meta.env.PHOTOBOOTH_INSTANCE as string | undefined) ?? 'dummy'

  const [session, setSession] = useState<BoothSessionState | null>(null)
  const [phase, setPhase] = useState<Phase>('starting')
  const [count, setCount] = useState(0)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<{ text: string; kind: CameraProblem | 'session' } | null>(
    null,
  )
  const videoRef = useRef<HTMLVideoElement>(null)
  const viewRef = useRef<CameraView | null>(null)
  const [live, setLive] = useState<CameraView | null>(null)
  const [devices, setDevices] = useState<CameraDevice[]>([])
  const [deviceId, setDeviceId] = useState<string | null>(() => rememberedCamera())
  const timers = useRef<number[]>([])
  // The photo waiting for its answer. A retry sends these very bytes again under the same key,
  // so a lost answer never turns into a second (different) photo (P67-002).
  const pending = useRef<PendingPhoto | null>(null)
  const camera = useMemo(() => given ?? chooseCamera(instance), [given, instance])

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
          navigate('/booth/frames', { replace: true }) // no frame chosen yet
          return
        }
        setSession(current)
        setPhase(current.state === 'capturing' ? 'ready' : 'complete')
      } catch {
        if (alive) navigate('/booth/frames', { replace: true })
      }
    })()
    return () => {
      alive = false
    }
  }, [api, navigate])

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
        // Once a camera is open the browser names the others, so the booth can offer a choice.
        const found = await camera.devices()
        if (alive) setDevices(found)
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
          navigate('/booth/frames', { replace: true })
          return
        }
      }
      setProblem({ text: 'That photo did not reach the booth. Try again.', kind: 'session' })
      setPhase('ready')
    }
  }, [api, later, navigate, next, seenSomebody, session])

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
      navigate('/booth', { replace: reason === 'timed-out' })
    },
    [api, clearTimers, navigate, session, stopCamera],
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
    if (!session || busy) return
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
      setBusy(false)
    }
  }

  const finish = async () => {
    if (!session || busy) return
    setBusy(true)
    try {
      const done = await api.finishCaptures(session.id)
      clearTimers()
      stopCamera() // the camera light goes out as soon as the photos are done
      setSession(done)
      setPhase('complete')
    } catch {
      setProblem({ text: 'The booth could not finish the session.', kind: 'session' })
    } finally {
      setBusy(false)
    }
  }

  if (menu.isPending || !session) {
    return <p className={styles.plain}>Loading…</p>
  }

  const tokens = menu.isSuccess ? menu.data.theme : {}
  const complete = session.taken >= session.expected_captures
  const canRetakeOne = capturing && session.retake_mode === 'per_photo'
  const canRetakeAll = capturing && session.retake_mode === 'all'

  return (
    <EventScreen tokens={tokens} className={styles.screen} label="Photo session">
      <div className={styles.header}>
        <EventHeading level={1}>{complete ? 'All photos taken' : 'Look at the camera'}</EventHeading>
        <p className={styles.progress} data-testid="capture-progress" role="status">
          {complete
            ? `${session.taken} of ${total} photos`
            : `Photo ${Math.min(taken + 1, total)} of ${total}`}
        </p>
        <ul className={styles.dots} aria-label="Photos taken">
          {session.shots.map((shot) => (
            <li
              key={shot.shot_index}
              className={styles.dot}
              data-done={shot.done ? '' : undefined}
              data-current={!complete && shot.shot_index === next?.shot_index ? '' : undefined}
              aria-label={`Photo ${shot.shot_index}${shot.done ? ', taken' : ''}`}
            />
          ))}
        </ul>
      </div>

      <div className={styles.stage}>
        <video
          ref={videoRef}
          className={styles.preview}
          data-mirrored={session.mirror ? '' : undefined}
          playsInline
          muted
          autoPlay
          aria-label="Camera preview"
        />
        {phase === 'counting' && (
          <p className={styles.countdown} data-testid="countdown" aria-live="assertive">
            {count > 0 ? count : 'Smile!'}
          </p>
        )}
        {phase === 'flash' && <div className={styles.flash} data-testid="flash" aria-hidden="true" />}
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

      <div className={styles.actions}>
        {devices.length > 1 && capturing && (
          <label className={styles.cameraPicker}>
            Camera
            <select
              className={styles.select}
              value={deviceId ?? devices[0]?.id ?? ''}
              onChange={(event) => {
                rememberCamera(event.target.value)
                setDeviceId(event.target.value)
              }}
            >
              {devices.map((device) => (
                <option key={device.id} value={device.id}>
                  {device.label}
                </option>
              ))}
            </select>
          </label>
        )}
        {complete ? (
          <>
            <EventText>
              {capturing
                ? 'Happy with these?'
                : 'The photos are ready for the next step.'}
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
    </EventScreen>
  )
}
