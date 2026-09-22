import { useEffect, useId, useRef, useState } from 'react'

import { RetryingImage } from '../ui/RetryingImage'
import { EventButton, EventHeading, EventText } from './EventUi'
import { planSummary, type GalleryFrame } from './framePlan'
import styles from './FrameGallery.module.css'

/**
 * The participant frame chooser. Used by the booth screen and, scaled down, by the admin preview,
 * so both always show the same thing. Participants only see the frame, its name and what it
 * means for the session; never where a frame came from or any admin action.
 */

interface FrameGalleryProps {
  frames: GalleryFrame[]
  allowSurprise: boolean
  /** The frame confirmed with "Use this frame" (null: nothing chosen yet). */
  selectedId: string | null
  onConfirm: (frame: GalleryFrame) => void | Promise<void>
  onStart: (frame: GalleryFrame) => void
  onChooseAgain: () => void
  /** Random source for "Surprise me" (injectable for tests). */
  random?: () => number
  /** Admin preview: smaller cards, no focus trapping side effects. */
  compact?: boolean
  busy?: boolean
}

const ALL = 'all'

export function FrameGallery({
  frames,
  allowSurprise,
  selectedId,
  onConfirm,
  onStart,
  onChooseAgain,
  random = Math.random,
  compact = false,
  busy = false,
}: FrameGalleryProps) {
  const [tab, setTab] = useState<string>(ALL)
  const [previewing, setPreviewing] = useState<GalleryFrame | null>(null)
  const openerRef = useRef<HTMLElement | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  const layouts: { key: string; label: string }[] = []
  for (const frame of frames) {
    if (!layouts.some((l) => l.key === frame.plan.template_key)) {
      layouts.push({ key: frame.plan.template_key, label: frame.plan.layout_label })
    }
  }
  // A tab whose last frame disappeared falls back to All.
  const activeTab = tab === ALL || layouts.some((l) => l.key === tab) ? tab : ALL
  const shown = activeTab === ALL ? frames : frames.filter((f) => f.plan.template_key === activeTab)
  const selected = frames.find((f) => f.id === selectedId) ?? null
  const surprise = allowSurprise && frames.length >= 2

  useEffect(() => {
    if (previewing) dialogRef.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus()
  }, [previewing])

  const open = (frame: GalleryFrame, opener: HTMLElement | null) => {
    openerRef.current = opener
    setPreviewing(frame)
  }
  const close = () => {
    setPreviewing(null)
    openerRef.current?.focus()
  }

  return (
    <div className={compact ? `${styles.gallery} ${styles.compact}` : styles.gallery} data-testid="frame-gallery">
      <EventHeading level={compact ? 3 : 1}>Choose your frame</EventHeading>
      <EventText muted>Tap a frame to see it bigger.</EventText>

      {layouts.length > 0 && (
        <div className={styles.tabs} role="tablist" aria-label="Frame sizes">
          {[{ key: ALL, label: 'All' }, ...layouts].map((layout) => (
            <button
              key={layout.key}
              type="button"
              role="tab"
              aria-selected={activeTab === layout.key}
              className={styles.tab}
              onClick={() => setTab(layout.key)}
            >
              {layout.label}
            </button>
          ))}
        </div>
      )}

      <ul className={styles.grid} aria-label="Frames">
        {surprise && (
          <li>
            <button
              type="button"
              className={`${styles.card} ${styles.surprise}`}
              onClick={(e) => {
                const pick = frames[Math.min(frames.length - 1, Math.floor(random() * frames.length))]
                if (pick) open(pick, e.currentTarget)
              }}
            >
              <span className={styles.surpriseMark} aria-hidden="true">
                ?
              </span>
              <span className={styles.cardName}>Surprise me</span>
              <span className={styles.cardSummary}>We pick a frame for you</span>
            </button>
          </li>
        )}
        {shown.map((frame) => {
          const isSelected = frame.id === selectedId
          return (
            <li key={frame.id}>
              <button
                type="button"
                className={styles.card}
                data-selected={isSelected ? '' : undefined}
                aria-pressed={isSelected}
                aria-label={`${frame.name}, ${planSummary(frame.plan)}${isSelected ? ', selected' : ''}`}
                onClick={(e) => open(frame, e.currentTarget)}
              >
                <span className={styles.imageBox}>
                  <RetryingImage
                    src={frame.previewUrl}
                    alt=""
                    className={styles.image}
                  />
                </span>
                <span className={styles.cardName}>{frame.name}</span>
                <span className={styles.cardSummary}>{planSummary(frame.plan)}</span>
                {isSelected && <span className={styles.selectedBadge}>Selected</span>}
              </button>
            </li>
          )
        })}
      </ul>

      {selected && (
        <div className={styles.selectionBar} role="status">
          <span className={styles.selectionText}>
            Selected: <strong>{selected.name}</strong> ({planSummary(selected.plan)})
          </span>
          <div className={styles.selectionActions}>
            <EventButton variant="primary" onClick={() => onStart(selected)}>
              Start with this frame
            </EventButton>
            <EventButton variant="secondary" onClick={onChooseAgain}>
              Choose a different frame
            </EventButton>
          </div>
        </div>
      )}

      {previewing && (
        <div className={styles.backdrop} onClick={close}>
          <div
            ref={dialogRef}
            className={styles.dialog}
            role="dialog"
            aria-modal={!compact}
            aria-labelledby={titleId}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === 'Escape') close()
            }}
          >
            <h2 id={titleId} className={styles.dialogTitle}>
              {previewing.name}
            </h2>
            <RetryingImage
              src={previewing.previewUrl}
              alt={`${previewing.name} with sample photos`}
              className={styles.dialogImage}
            />
            <p className={styles.dialogSummary}>{planSummary(previewing.plan)}</p>
            <div className={styles.dialogActions}>
              <EventButton
                variant="primary"
                data-autofocus=""
                disabled={busy}
                onClick={() => {
                  const frame = previewing
                  void Promise.resolve(onConfirm(frame)).then(() => setPreviewing(null))
                }}
              >
                Use this frame
              </EventButton>
              <EventButton variant="secondary" onClick={close}>
                Back
              </EventButton>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
