import { useEffect, useId, useRef } from 'react'

import { EventButton } from '../../shared/eventUi/EventUi'
import styles from './FinishDialog.module.css'

/**
 * "Finish your photos?": the one question before the finished photos are made.
 *
 * A centred pop-up on the dimmed event overlay. The focus starts on the main answer, stays
 * inside while it is open, and Escape or the backdrop keep decorating. Nothing is made until
 * "Make my photos", and a second tap can not ask twice (the page leaves this state at once).
 */

interface FinishDialogProps {
  onKeep: () => void
  onFinish: () => void
}

export function FinishDialog({ onKeep, onFinish }: FinishDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const textId = useId()

  useEffect(() => {
    dialogRef.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus()
  }, [])

  return (
    <div
      className={styles.backdrop}
      data-testid="finish-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) event.preventDefault()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onKeep()
      }}
    >
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={textId}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation()
            onKeep()
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
          Finish your photos?
        </h2>
        <p id={textId} className={styles.text}>
          Your photos will be made just as you see them. You can&apos;t change them after this.
        </p>
        <div className={styles.actions}>
          <EventButton variant="primary" data-autofocus="" onClick={onFinish}>
            Make my photos
          </EventButton>
          <EventButton variant="secondary" onClick={onKeep}>
            Keep decorating
          </EventButton>
        </div>
      </div>
    </div>
  )
}
