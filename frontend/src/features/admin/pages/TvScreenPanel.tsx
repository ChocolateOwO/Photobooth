import { useCallback, useEffect, useState } from 'react'

import type { PcCamera, ScreenDetails, TvCode } from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import styles from './BoothTestPage.module.css'

/**
 * "TV screen": the booth on a TV's browser, photographing with this PC's camera.
 *
 * The organizer picks which of this PC's cameras the TV booth uses (a still of each tells them
 * apart) and shows a six-digit code to type on the TV. Admin itself never opens on the TV.
 */
export function TvScreenPanel() {
  const admin = useAdminApi()
  const [screen, setScreen] = useState<ScreenDetails | null>(null)
  const [cameras, setCameras] = useState<PcCamera[] | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [code, setCode] = useState<TvCode | null>(null)
  const [secondsLeft, setSecondsLeft] = useState(0)
  const [stillAt, setStillAt] = useState(() => Date.now())

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const [details, found] = await Promise.all([admin.screen(), admin.pcCameras()])
        if (!alive) return
        setScreen(details)
        setCameras(found)
      } catch {
        if (alive) setProblem('The TV screen settings could not be loaded. Reload the page.')
      }
    })()
    return () => {
      alive = false
    }
  }, [admin])

  // The code counts down on screen; at zero it is gone (the server forgets it too).
  useEffect(() => {
    if (!code) return
    const ends = Date.now() + code.expires_in_seconds * 1000
    const tick = () => {
      const left = Math.max(0, Math.round((ends - Date.now()) / 1000))
      setSecondsLeft(left)
      if (left === 0) setCode(null)
    }
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [code])

  const choose = useCallback(
    async (index: number | null) => {
      try {
        setScreen(await admin.choosePcCamera(index))
        setStillAt(Date.now())
        setProblem(null)
      } catch {
        setProblem('The camera could not be changed. Try again.')
      }
    },
    [admin],
  )

  const showCode = async () => {
    try {
      setCode(await admin.tvCode())
      setProblem(null)
    } catch {
      setProblem('A TV code could not be made. Try again.')
    }
  }

  const chosen = screen?.camera_index ?? null
  const shown = chosen ?? 0
  const loading = screen === null && problem === null

  return (
    <section className={styles.tv} aria-labelledby="tv-screen-heading">
      <h2 id="tv-screen-heading" className={styles.subheading}>
        TV screen
      </h2>
      <p className={styles.intro}>
        Guests can use the booth on a TV on the same Wi-Fi. The TV shows the booth and takes the
        touches; this PC&apos;s camera takes the photos.
      </p>

      {loading && <p className={styles.hint}>Loading…</p>}
      {problem && (
        <p className={styles.problem} role="alert">
          {problem}
        </p>
      )}

      {screen && !screen.tv_url && (
        <p className={styles.hint}>
          The TV screen is switched off for this booth. Add PHOTOBOOTH_SCREEN_PORT to its settings
          file and start the booth again.
        </p>
      )}

      {screen && (
        <>
          <label className={styles.field}>
            <span className={styles.label}>Camera for the TV booth</span>
            <select
              className={styles.select}
              value={chosen === null ? '' : String(chosen)}
              onChange={(event) =>
                void choose(event.target.value === '' ? null : Number(event.target.value))
              }
            >
              <option value="">This PC&apos;s first camera</option>
              {(cameras ?? []).map((camera) => (
                <option key={camera.index} value={camera.index}>
                  {camera.label}
                </option>
              ))}
            </select>
          </label>
          {cameras !== null && cameras.length === 0 && (
            <p className={styles.hint}>No camera answered. Plug one in, then reload this page.</p>
          )}
          <figure className={styles.still}>
            <img
              src={`/api/admin/screen/cameras/${shown}.jpg?at=${stillAt}`}
              alt={`What camera ${shown + 1} sees now`}
              width={320}
              height={240}
            />
            <figcaption className={styles.hint}>
              What the chosen camera sees.{' '}
              <button
                type="button"
                className={styles.link}
                onClick={() => setStillAt(Date.now())}
              >
                Refresh
              </button>
            </figcaption>
          </figure>

          {screen.tv_url && (
            <div className={styles.field}>
              <span className={styles.label}>Connect a TV</span>
              <p className={styles.hint}>
                On the TV, open <strong className={styles.address}>{screen.tv_url}</strong> and
                type the code.
              </p>
              {code ? (
                <p className={styles.code} aria-live="polite">
                  <span data-testid="tv-code">{code.code}</span>
                  <span className={styles.hint}>valid for {secondsLeft} s</span>
                </p>
              ) : null}
              <button type="button" className={styles.start} onClick={() => void showCode()}>
                {code ? 'Show a new TV code' : 'Show TV code'}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
