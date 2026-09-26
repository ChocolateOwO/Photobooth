import { useCallback, useEffect, useState } from 'react'

import { useAdminApi } from '../../../shared/api/AdminApiContext'
import {
  BrowserCamera,
  rememberCamera,
  rememberedCamera,
  type CameraDevice,
} from '../../../shared/camera/camera'
import {
  BoothServicesContext,
  useProfileTestBooth,
  type BoothStep,
} from '../../booth/boothServices'
import { BoothStartPage } from '../../booth/BoothStartPage'
import { CapturePage } from '../../booth/CapturePage'
import { FrameSelectPage } from '../../booth/FrameSelectPage'
import { useProfiles } from '../api/hooks'
import styles from './BoothTestPage.module.css'

/**
 * "Test booth": the organizer tries the booth on this machine, with the real camera.
 *
 * The screens below are the booth's own — the same start screen, frame carousel, confirmation
 * pop-up, countdown, photos and review a guest sees — running inside this page rather than at
 * the booth address. The profile under test is only read: it is never activated or changed, and
 * everything the test takes is scratch data that goes when the test does.
 */

function TestBooth({ profileId }: { profileId: string }) {
  // The booth's own screens, in the booth's own order, without leaving the Admin page.
  const [step, setStep] = useState<BoothStep>('start')
  const go = useCallback((next: BoothStep) => setStep(next), [])
  const booth = useProfileTestBooth(profileId, go)
  return (
    <BoothServicesContext.Provider value={booth}>
      {step === 'start' && <BoothStartPage />}
      {step === 'frames' && <FrameSelectPage />}
      {step === 'capture' && <CapturePage />}
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
    void admin.clearBoothTests().catch(() => undefined)
  }

  if (running && chosen) {
    return (
      <section className={styles.runner} aria-label="Booth test">
        <div className={styles.bar}>
          <p className={styles.badge} data-testid="test-banner">
            TEST — this is not a guest session, and nothing is kept
          </p>
          <button type="button" className={styles.exit} onClick={stop}>
            Exit test
          </button>
        </div>
        <div className={styles.screen} data-testid="booth-test-screen">
          <TestBooth key={`${chosen}-${round}`} profileId={chosen} />
        </div>
      </section>
    )
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
        onClick={() => setRunning(true)}
      >
        Start booth test
      </button>
    </section>
  )
}
