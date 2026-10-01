import { useEffect, useId, useRef } from 'react'

import { EventButton } from '../../shared/eventUi/EventUi'
import styles from './PhotoDialog.module.css'

/**
 * One photo, as large as the screen allows and in its own proportions.
 *
 * It shows a picture that is already stored, so opening and closing it never touches the camera.
 * The focus goes inside while it is open and back to whatever opened it afterwards.
 */

interface PhotoDialogProps {
  shotIndex: number
  url: string
  onClose: () => void
  /** Offered only where the event allows a single photo to be taken again. */
  onRetake?: (() => void) | undefined
  busy?: boolean
  /** Show the photo the way the print will have it (the event's mirror setting). */
  mirror?: boolean
}

export function PhotoDialog({
  shotIndex,
  url,
  onClose,
  onRetake,
  busy = false,
  mirror = false,
}: PhotoDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    dialogRef.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus()
  }, [])

  return (
    <div
      className={styles.backdrop}
      data-testid="photo-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) event.preventDefault()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
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
            onClose()
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
        <h2 id={titleId} className={styles.title}>
          Photo {shotIndex}
        </h2>
        {/* The whole photo, in its own proportions: never cropped, never stretched. */}
        <img
          src={url}
          alt={`Photo ${shotIndex}`}
          className={styles.photo}
          data-mirrored={mirror ? '' : undefined}
          data-testid="photo-large"
        />
        <div className={styles.actions}>
          <EventButton variant="primary" data-autofocus="" onClick={onClose}>
            Close
          </EventButton>
          {onRetake && (
            <EventButton variant="secondary" disabled={busy} onClick={onRetake}>
              Retake this photo
            </EventButton>
          )}
        </div>
      </div>
    </div>
  )
}
