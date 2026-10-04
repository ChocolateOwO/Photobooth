import { useCallback, useEffect, useState } from 'react'

import { useAdminApi } from '../../../shared/api/AdminApiContext'
import {
  BrowserCamera,
  rememberCamera,
  rememberedCamera,
  type CameraDevice,
} from '../../../shared/camera/camera'
import { themeStyle } from '../../../shared/eventTheme/theme'
import { useEnterImmersive } from '../../../shared/ui/immersive'
import { useBoothMenu } from '../../booth/boothMenu'
import {
  BoothServicesContext,
  useProfileTestBooth,
  type BoothStep,
} from '../../booth/boothServices'
import { BoothErrorBoundary } from '../../booth/BoothSafety'
import { BoothStartPage } from '../../booth/BoothStartPage'
import { CapturePage } from '../../booth/CapturePage'
import { DecoratePage } from '../../booth/DecoratePage'
import { DeliveryPage } from '../../booth/DeliveryPage'
import { FrameSelectPage } from '../../booth/FrameSelectPage'
import { useProfiles } from '../api/hooks'
import styles from './BoothTestPage.module.css'
import { TvScreenPanel } from './TvScreenPanel'

/**
 * "Test booth": the organizer tries the booth on this machine, with the real camera.
 *
 * Setting it up is an ordinary Admin page. Once the test starts, the booth's own screens — the
 * same start screen, frame carousel, confirmation pop-up, countdown, photos and review a guest
 * sees — take the whole display: the Admin header, navigation and page frame step aside, the
 * browser is asked for fullscreen, and only a small TEST mark and Exit test stay on top, in the
 * event's own colours. The profile under test is only read: never activated, never changed, and
 * everything the test takes goes when the test does.
 */

/**
 * Ask for the whole display. A browser that refuses, or has no Fullscreen API at all, changes
 * nothing: the booth still fills the window and the test runs exactly the same. Leaving
 * fullscreen with Escape is the browser's business and never touches the visit.
 */
function askForFullscreen(): void {
  const page = document.documentElement
  if (document.fullscreenElement || typeof page.requestFullscreen !== 'function') return
  try {
    void page.requestFullscreen().catch(() => undefined)
  } catch {
    // Refused outright; the booth is immersive either way.
  }
}

function leaveFullscreen(): void {
  if (!document.fullscreenElement || typeof document.exitFullscreen !== 'function') return
  try {
    void document.exitFullscreen().catch(() => undefined)
  } catch {
    // Already out of fullscreen, or the browser will not say; nothing depends on it.
  }
}

/** The mark and the way out, over the booth, wearing the event's theme. */
function TestChrome({ onExit }: { onExit: () => void }) {
  const menu = useBoothMenu()
  const tokens = menu.isSuccess ? menu.data.theme : {}
  return (
    <div className={styles.chrome} style={themeStyle(tokens)}>
      <p className={styles.badge} data-testid="test-banner">
        TEST
      </p>
      <button type="button" className={styles.exit} onClick={onExit}>
        Exit test
      </button>
    </div>
  )
}

function TestBooth({ profileId, onExit }: { profileId: string; onExit: () => void }) {
  // The booth's own screens, in the booth's own order, without leaving the Admin page.
  const [step, setStep] = useState<BoothStep>('start')
  const go = useCallback((next: BoothStep) => setStep(next), [])
  const booth = useProfileTestBooth(profileId, go)
  // Immersive from the first frame of the test, whatever the booth screen is still loading.
  useEnterImmersive()
  return (
    <BoothServicesContext.Provider value={booth}>
      {/* A screen that fails shows "Start again", which goes back to the test's start. */}
      <BoothErrorBoundary key={step} onRestart={() => go('start')}>
        {step === 'start' && <BoothStartPage />}
        {step === 'frames' && <FrameSelectPage />}
        {step === 'capture' && <CapturePage />}
        {step === 'decorate' && <DecoratePage />}
        {step === 'done' && <DeliveryPage />}
      </BoothErrorBoundary>
      <TestChrome onExit={onExit} />
    </BoothServicesContext.Provider>
  )
}

export function BoothTestPage() {
  const admin = useAdminApi()
  const profiles = useProfiles()
  const [profileId, setProfileId] = useState<string | null>(null)
  const [deviceId, setDeviceId] = useState<string | null>(() => rememberedCamera())
  // null until the browser has answered, so the hint below is never shown over a list still coming.
  const [cameras, setCameras] = useState<CameraDevice[] | null>(null)
  const [running, setRunning] = useState(false)
  const [round, setRound] = useState(0)

  const live = profiles.data ?? []
  const active = live.find((profile) => profile.is_active) ?? live[0] ?? null
  const chosen = profileId ?? active?.id ?? null

  // The cameras of this machine, named once the browser is willing to name them.
  useEffect(() => {
    let alive = true
    void (async () => {
      const found = await new BrowserCamera().devices().catch(() => [])
      if (alive) setCameras(found)
    })()
    return () => {
      alive = false
    }
  }, [running])

  // Whatever an earlier test left behind goes when this page opens, and when it closes.
  useEffect(() => {
    void admin.clearBoothTests().catch(() => undefined)
    return () => {
      void admin.clearBoothTests().catch(() => undefined)
    }
  }, [admin])

  const stop = () => {
    setRunning(false)
    setRound((count) => count + 1) // a fresh booth next time, with nothing of this one left
    leaveFullscreen()
    void admin.clearBoothTests().catch(() => undefined)
  }

  if (running && chosen) {
    return <TestBooth key={`${chosen}-${round}`} profileId={chosen} onExit={stop} />
  }

  return (
    <section className={styles.page} aria-labelledby="booth-test-heading">
      <h1 id="booth-test-heading" className={styles.heading}>
        Test booth
      </h1>
      <p className={styles.intro}>
        Try the booth on this machine with the real camera. The event you pick is only tried: it
        is not activated, nothing about it changes, and the photos of a test are thrown away.
      </p>

      <label className={styles.field}>
        <span className={styles.label}>Event to try</span>
        <select
          className={styles.select}
          value={chosen ?? ''}
          onChange={(event) => setProfileId(event.target.value)}
          disabled={live.length === 0}
        >
          {live.map((profile) => (
            <option key={profile.id} value={profile.id}>
              {profile.settings.name}
              {profile.is_active ? ' (live now)' : ''}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.field}>
        <span className={styles.label}>Camera</span>
        <select
          className={styles.select}
          value={deviceId ?? ''}
          onChange={(event) => {
            const wanted = event.target.value || null
            rememberCamera(wanted)
            setDeviceId(wanted)
          }}
        >
          <option value="">This machine&apos;s usual camera</option>
          {(cameras ?? []).map((camera) => (
            <option key={camera.id} value={camera.id}>
              {camera.label}
            </option>
          ))}
        </select>
      </label>
      {cameras !== null && cameras.length === 0 && (
        <p className={styles.hint}>
          Cameras are named once the browser has been allowed to use one; start the test and allow
          the camera, then come back here to choose another.
        </p>
      )}

      <button
        type="button"
        className={styles.start}
        disabled={!chosen}
        onClick={() => {
          // Fullscreen is only granted from a gesture like this one; a refusal changes nothing.
          askForFullscreen()
          setRunning(true)
        }}
      >
        Start booth test
      </button>

      <TvScreenPanel />
    </section>
  )
}
