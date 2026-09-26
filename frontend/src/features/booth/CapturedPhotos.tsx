import { useEffect, useId, useRef, useState } from 'react'

import type { ShotState } from '../../shared/api/client'
import { EventButton } from '../../shared/eventUi/EventUi'
import styles from './CapturedPhotos.module.css'

/**
 * The photos taken so far, and a large look at any one of them.
 *
 * Every shot of the chosen frame has its own place here, in order. A place stays empty until its
 * own photo arrives: a picture is only ever shown under its own number, so nobody can mistake
 * one photo for another. Looking at a photo never touches the camera.
 */

interface CapturedPhotosProps {
  shots: ShotState[]
  /** The photo of one shot, for an <img>; null while that shot has none. */
  photoUrl: (shot: ShotState) => string | null
  /** Offered only where the event allows a single photo to be taken again. */
  onRetake?: ((shotIndex: number) => void) | undefined
  busy?: boolean
  /** Bigger pictures on the review screen than in the strip beside the camera. */
  large?: boolean
}

export function CapturedPhotos({
  shots,
  photoUrl,
  onRetake,
  busy = false,
  large = false,
}: CapturedPhotosProps) {
  const [looking, setLooking] = useState<ShotState | null>(null)
  const openerRef = useRef<HTMLButtonElement | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  const open = (shot: ShotState, opener: HTMLButtonElement) => {
    openerRef.current = opener
    setLooking(shot)
  }
  const close = () => {
    setLooking(null)
    openerRef.current?.focus()
  }

  useEffect(() => {
    if (looking) dialogRef.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus()
  }, [looking])

  // The photo on screen follows the session: a retake replaces it in place, and while that shot
  // has no photo (just retaken) there is nothing to look at, so the dialog simply goes.
  const shown = looking ? shots.find((shot) => shot.shot_index === looking.shot_index) : null
  const shownUrl = shown ? photoUrl(shown) : null

  return (
    <>
      <ul
        className={large ? `${styles.strip} ${styles.big}` : styles.strip}
        aria-label="Photos taken"
        data-testid="captured-photos"
      >
        {shots.map((shot) => {
          const url = photoUrl(shot)
          return (
            <li key={shot.shot_index} className={styles.slot} data-testid="captured-photo">
              {url ? (
                <button
                  type="button"
                  className={styles.photoButton}
                  aria-label={`Photo ${shot.shot_index}, see it bigger`}
                  onClick={(event) => open(shot, event.currentTarget)}
                >
                  <img src={url} alt={`Photo ${shot.shot_index}`} className={styles.photo} />
                </button>
              ) : (
                // Nothing here yet: an empty place, never another shot's picture.
                <span className={styles.empty} aria-label={`Photo ${shot.shot_index}, not taken yet`} />
              )}
              <span className={styles.label}>Photo {shot.shot_index}</span>
            </li>
          )
        })}
      </ul>

      {shown && shownUrl && (
        <div
          className={styles.backdrop}
          data-testid="photo-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) event.preventDefault()
          }}
          onClick={(event) => {
            if (event.target === event.currentTarget) close()
          }}
        >
          <div
            ref={dialogRef}
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.stopPropagation()
                close()
                return
              }
              if (event.key !== 'Tab') return
              const focusable = [
                ...(dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled)') ?? []),
              ]
              const first = focusable[0]
              const last = focusable[focusable.length - 1]
              if (!first || !last) return
              if (event.shiftKey && document.activeElement === first) {
                event.preventDefault()
                last.focus()
              } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault()
                first.focus()
              }
            }}
          >
            <h2 id={titleId} className={styles.dialogTitle}>
              Photo {shown.shot_index}
            </h2>
            {/* The whole photo, in its own proportions: never cropped, never stretched. */}
            <img
              src={shownUrl}
              alt={`Photo ${shown.shot_index}`}
              className={styles.dialogPhoto}
              data-testid="photo-large"
            />
            <div className={styles.dialogActions}>
              <EventButton variant="primary" data-autofocus="" onClick={close}>
                Close
              </EventButton>
              {onRetake && (
                <EventButton
                  variant="secondary"
                  disabled={busy}
                  onClick={() => {
                    const shot = shown.shot_index
                    close()
                    onRetake(shot)
                  }}
                >
                  Retake this photo
                </EventButton>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
