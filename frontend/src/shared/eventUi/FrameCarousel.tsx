import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { RetryingImage } from '../ui/RetryingImage'
import { EventButton, EventHeading } from './EventUi'
import { planSummary, type GalleryFrame } from './framePlan'
import styles from './FrameCarousel.module.css'

/**
 * The participant frame chooser: one full-size frame at a time in a vertical scroll-snap
 * carousel. Used by the booth screen and, scaled down, by the admin preview, so both always show
 * the same thing. Participants only see the frame, its name and what it means for the session;
 * never where a frame came from or any admin action. Moving between frames never chooses one:
 * only "Use this frame" does.
 */

interface FrameCarouselProps {
  frames: GalleryFrame[]
  allowSurprise: boolean
  /** The frame confirmed with "Use this frame" (null: nothing chosen yet). */
  selectedId: string | null
  /** Where to open the carousel (a frame chosen earlier in this session). */
  startAtId?: string | null
  onConfirm: (frame: GalleryFrame) => void | Promise<void>
  onStart: (frame: GalleryFrame) => void
  onChooseAgain: () => void
  /** Moving to another frame abandons a confirmation that is still on its way. */
  onCancel?: () => void
  /** Random source for "Surprise me" (injectable for tests). */
  random?: () => number
  /** Shown inside the admin preview: a smaller heading level. */
  compact?: boolean
  busy?: boolean
}

const ALL = 'all'
/** Only the frame in view and its two neighbours load their sample image. */
const PRELOAD = 1

function reducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

export function FrameCarousel({
  frames,
  allowSurprise,
  selectedId,
  startAtId = null,
  onConfirm,
  onStart,
  onChooseAgain,
  onCancel,
  random = Math.random,
  compact = false,
  busy = false,
}: FrameCarouselProps) {
  const [tab, setTab] = useState<string>(ALL)
  const [index, setIndex] = useState(0)
  const [hinted, setHinted] = useState(false)
  const trackRef = useRef<HTMLUListElement>(null)
  const openedAt = useRef(startAtId ?? selectedId)

  const layouts: { key: string; label: string }[] = []
  for (const frame of frames) {
    if (!layouts.some((l) => l.key === frame.plan.template_key)) {
      layouts.push({ key: frame.plan.template_key, label: frame.plan.layout_label })
    }
  }
  // A tab whose last frame disappeared falls back to All.
  const activeTab = tab === ALL || layouts.some((l) => l.key === tab) ? tab : ALL
  const shown = activeTab === ALL ? frames : frames.filter((f) => f.plan.template_key === activeTab)
  const tabs = [{ key: ALL, label: 'All' }, ...layouts]
  const selected = frames.find((f) => f.id === selectedId) ?? null
  const surprise = allowSurprise && shown.length >= 2
  const at = Math.min(index, Math.max(0, shown.length - 1))
  const current = shown[at] ?? null

  const scrollTo = (next: number, smooth: boolean) => {
    const track = trackRef.current
    if (!track) return
    const top = next * track.clientHeight
    if (typeof track.scrollTo === 'function') {
      track.scrollTo({ top, behavior: smooth && !reducedMotion() ? 'smooth' : 'auto' })
    } else {
      track.scrollTop = top // environments without smooth scrolling (and jsdom)
    }
  }

  // A changed filter rebuilds the track: start it at the top before anything is painted, so the
  // browser can not keep the frame that was in view (scroll anchoring) while the carousel is on
  // the first frame of the new size.
  useLayoutEffect(() => {
    scrollTo(0, false)
  }, [activeTab])

  // The frame chosen earlier in this session is the one the carousel opens on.
  useEffect(() => {
    const start = frames.findIndex((f) => f.id === openedAt.current)
    if (start > 0) {
      setIndex(start)
      scrollTo(start, false)
    }
    // Only when the carousel is first shown a list of frames.
  }, [frames.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // A gesture that stops between two frames settles on the nearest one, so a frame is never left
  // half shown (CSS snapping already does this for most gestures; this also covers the rest).
  const settleTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(settleTimer.current), [])
  const settleSoon = () => {
    window.clearTimeout(settleTimer.current)
    settleTimer.current = window.setTimeout(() => {
      const track = trackRef.current
      if (!track || track.clientHeight <= 0) return
      const nearest = Math.round(track.scrollTop / track.clientHeight)
      if (Math.abs(track.scrollTop - nearest * track.clientHeight) > 2) scrollTo(nearest, true)
    }, 140)
  }

  const goTo = (next: number) => {
    const target = Math.max(0, Math.min(shown.length - 1, next))
    setHinted(true)
    if (target === at) return
    onCancel?.() // a confirmation still on its way belongs to the frame being left
    setIndex(target)
    scrollTo(target, true)
  }

  const chooseTab = (key: string) => {
    setTab(key)
    setIndex(0)
    setHinted(true)
    onCancel?.()
    scrollTo(0, false)
  }

  return (
    <div className={styles.carousel} data-testid="frame-carousel">
      <div className={styles.header}>
        <EventHeading level={compact ? 3 : 1}>Choose your frame</EventHeading>
        <div className={styles.controls}>
          {layouts.length > 0 && (
            <div className={styles.tabs} role="tablist" aria-label="Frame sizes">
              {tabs.map((layout, position) => (
                <button
                  key={layout.key}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === layout.key}
                  tabIndex={activeTab === layout.key ? 0 : -1}
                  className={styles.tab}
                  onClick={() => chooseTab(layout.key)}
                  onKeyDown={(e) => {
                    // Arrow keys, Home and End move between the size pills (roving focus).
                    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key]
                    const target =
                      e.key === 'Home'
                        ? 0
                        : e.key === 'End'
                          ? tabs.length - 1
                          : step
                            ? position + step
                            : null
                    if (target === null) return
                    e.preventDefault()
                    const next = (target + tabs.length) % tabs.length
                    const nextTab = tabs[next]
                    if (!nextTab) return
                    chooseTab(nextTab.key)
                    const buttons =
                      e.currentTarget.parentElement?.querySelectorAll<HTMLElement>('[role="tab"]')
                    buttons?.[next]?.focus()
                  }}
                >
                  {layout.label}
                </button>
              ))}
            </div>
          )}
          {surprise && (
            <button
              type="button"
              className={styles.surprise}
              onClick={() => goTo(Math.min(shown.length - 1, Math.floor(random() * shown.length)))}
            >
              Surprise me
            </button>
          )}
        </div>
      </div>

      {shown.length === 0 ? (
        <p className={styles.empty} role="status">
          No frames are available for this size.
        </p>
      ) : (
        <div
          className={styles.stage}
          onKeyDown={(e) => {
            const step = { ArrowDown: 1, PageDown: 1, ArrowUp: -1, PageUp: -1 }[e.key]
            const target = e.key === 'Home' ? 0 : e.key === 'End' ? shown.length - 1 : step ? at + step : null
            if (target === null) return
            e.preventDefault()
            goTo(target)
          }}
        >
          <ul
            className={styles.track}
            ref={trackRef}
            aria-label="Choose your frame"
            aria-roledescription="carousel"
            tabIndex={0}
            onScroll={(e) => {
              const track = e.currentTarget
              const height = track.clientHeight
              if (height <= 0) return
              const settled = Math.max(0, Math.min(shown.length - 1, Math.round(track.scrollTop / height)))
              setHinted(true)
              settleSoon()
              if (settled !== at) {
                onCancel?.()
                setIndex(settled)
              }
            }}
          >
            {shown.map((frame, position) => {
              const isCurrent = position === at
              const near = Math.abs(position - at) <= PRELOAD
              return (
                <li
                  key={frame.id}
                  className={styles.slide}
                  data-testid="frame-slide"
                  data-current={isCurrent ? '' : undefined}
                  aria-roledescription="slide"
                  aria-label={`${frame.name}, ${position + 1} of ${shown.length}`}
                  // Only the frame in view takes clicks and the keyboard; the others are scenery.
                  {...(isCurrent ? {} : { inert: true })}
                >
                  <div className={styles.imageBox}>
                    {near ? (
                      <RetryingImage
                        src={frame.previewUrl}
                        alt={`${frame.name} with sample photos`}
                        className={styles.image}
                      />
                    ) : (
                      <span className={styles.imagePlaceholder} aria-hidden="true" />
                    )}
                  </div>
                  <div className={styles.meta}>
                    <p className={styles.name}>{frame.name}</p>
                    <p className={styles.summary}>{planSummary(frame.plan)}</p>
                    {/* Only the frame in view can be chosen, so "Use this frame" is never
                        ambiguous, on screen or for a screen reader. */}
                    {isCurrent && (
                      <EventButton variant="primary" disabled={busy} onClick={() => void onConfirm(frame)}>
                        Use this frame
                      </EventButton>
                    )}
                    <p className={styles.position}>
                      {position + 1} of {shown.length}
                    </p>
                  </div>
                </li>
              )
            })}
          </ul>

          <div className={styles.arrows}>
            <button
              type="button"
              className={styles.arrow}
              aria-label="Previous frame"
              disabled={at === 0}
              onClick={() => goTo(at - 1)}
            >
              <span aria-hidden="true">▲</span>
            </button>
            <button
              type="button"
              className={styles.arrow}
              aria-label="Next frame"
              disabled={at >= shown.length - 1}
              onClick={() => goTo(at + 1)}
            >
              <span aria-hidden="true">▼</span>
            </button>
          </div>

          {shown.length > 1 && (
            <div className={styles.dots} role="group" aria-label="Frame positions">
              {shown.map((frame, position) => (
                <button
                  key={frame.id}
                  type="button"
                  className={styles.dot}
                  aria-label={`Show ${frame.name}`}
                  aria-current={position === at}
                  onClick={() => goTo(position)}
                />
              ))}
            </div>
          )}

          {!hinted && shown.length > 1 && (
            <p className={styles.hint}>Swipe or scroll to see the next frame</p>
          )}

          {/* Screen readers follow the carousel even when it moved by a swipe or the wheel. */}
          <p className={styles.announce} role="status">
            {current ? `${current.name}, ${planSummary(current.plan)}, ${at + 1} of ${shown.length}` : ''}
          </p>
        </div>
      )}

      {selected && (
        <div className={styles.selectionBar} role="status">
          <span className={styles.selectionText}>
            Selected: <strong>{selected.name}</strong> ({planSummary(selected.plan)})
          </span>
          <div className={styles.selectionActions}>
            <EventButton variant="primary" disabled={busy} onClick={() => onStart(selected)}>
              Start with this frame
            </EventButton>
            <EventButton variant="secondary" onClick={onChooseAgain}>
              Choose a different frame
            </EventButton>
          </div>
        </div>
      )}
    </div>
  )
}
