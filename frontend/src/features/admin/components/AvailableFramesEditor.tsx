import { useState, type DragEvent } from 'react'
import { Link } from 'react-router'

import type { Frame, TemplateSummary } from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import { RetryingImage } from '../../../shared/ui/RetryingImage'
import { layoutLabel } from '../frameCatalog'
import styles from './AvailableFramesEditor.module.css'

interface AvailableFramesEditorProps {
  frames: Frame[] | undefined
  loadFailed: boolean
  onRetry: () => void
  templates: TemplateSummary[]
  /** Frame ids offered to participants, in display order. */
  available: string[]
  onChange: (ids: string[]) => void
  allowSurprise: boolean
  onSurpriseChange: (allow: boolean) => void
  disabled: boolean
}

const ALL = 'all'

/**
 * Which frames participants may choose from, and in what order. Only on/off and order live here;
 * everything else about a frame (files, replace, rename, delete) stays on the Frames page.
 */
export function AvailableFramesEditor({
  frames,
  loadFailed,
  onRetry,
  templates,
  available,
  onChange,
  allowSurprise,
  onSurpriseChange,
  disabled,
}: AvailableFramesEditorProps) {
  const api = useAdminApi()
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState(ALL)
  const [dragging, setDragging] = useState<string | null>(null)
  const locked = disabled || frames === undefined

  const labelOf = (key: string) => {
    const template = templates.find((t) => t.key === key)
    return template ? layoutLabel(template) : key
  }
  const matches = (frame: Frame) =>
    (tab === ALL || frame.template_key === tab) &&
    frame.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())

  const byId = new Map((frames ?? []).map((f) => [f.id, f]))
  const enabled = available.map((id) => byId.get(id)).filter((f): f is Frame => f !== undefined)
  const enabledShown = enabled.filter(matches)
  const others = (frames ?? []).filter((f) => !available.includes(f.id) && matches(f))
  const count = enabled.length

  const toggle = (frame: Frame, on: boolean) =>
    onChange(on ? [...available, frame.id] : available.filter((id) => id !== frame.id))

  /** Move among the rows shown right now (search and tab respected), in the global order. */
  const move = (frame: Frame, step: -1 | 1) => {
    const shownIndex = enabledShown.findIndex((f) => f.id === frame.id)
    const neighbour = enabledShown[shownIndex + step]
    if (!neighbour) return
    const next = [...available]
    const a = next.indexOf(frame.id)
    const b = next.indexOf(neighbour.id)
    next[a] = neighbour.id
    next[b] = frame.id
    onChange(next)
  }

  const dropOn = (target: Frame, e: DragEvent<HTMLLIElement>) => {
    e.preventDefault()
    if (!dragging || dragging === target.id) return
    const without = available.filter((id) => id !== dragging)
    without.splice(without.indexOf(target.id), 0, dragging)
    onChange(without)
    setDragging(null)
  }

  const setLayout = (key: string, on: boolean) => {
    const layoutIds = (frames ?? []).filter((f) => f.template_key === key).map((f) => f.id)
    onChange(
      on
        ? [...available, ...layoutIds.filter((id) => !available.includes(id))]
        : available.filter((id) => !layoutIds.includes(id)),
    )
  }

  const layoutKeys = templates.map((t) => t.key).filter((key) => tab === ALL || key === tab)

  const row = (frame: Frame, on: boolean, index: number) => (
    <li
      key={frame.id}
      className={styles.row}
      data-testid="available-frame-row"
      data-enabled={on ? '' : undefined}
      draggable={on && !locked}
      onDragStart={() => setDragging(frame.id)}
      onDragEnd={() => setDragging(null)}
      onDragOver={(e) => {
        if (on && dragging) e.preventDefault()
      }}
      onDrop={(e) => on && dropOn(frame, e)}
    >
      {on && (
        <span className={styles.handle} aria-hidden="true" title="Drag to reorder">
          ⋮⋮
        </span>
      )}
      <RetryingImage
        src={api.framePreviewUrl(frame.id, 1, frame.sha256)}
        alt=""
        className={styles.thumb}
      />
      <span className={styles.name}>{frame.name}</span>
      <span className={styles.badge}>{labelOf(frame.template_key)}</span>
      <label className={styles.switch}>
        <input
          type="checkbox"
          role="switch"
          checked={on}
          disabled={locked}
          onChange={(e) => toggle(frame, e.target.checked)}
          aria-label={`Show ${frame.name} (${labelOf(frame.template_key)}) to participants`}
        />
        <span aria-hidden="true">{on ? 'On' : 'Off'}</span>
      </label>
      {on && (
        <span className={styles.moves}>
          <button
            type="button"
            onClick={() => move(frame, -1)}
            disabled={locked || index === 0}
            aria-label={`Move ${frame.name} up`}
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => move(frame, 1)}
            disabled={locked || index === enabledShown.length - 1}
            aria-label={`Move ${frame.name} down`}
          >
            ↓
          </button>
        </span>
      )}
    </li>
  )

  return (
    <section className={styles.section} aria-labelledby="available-frames-heading">
      <div className={styles.header}>
        <h2 id="available-frames-heading" className={styles.heading}>
          Available frames for participants
        </h2>
        <Link to="/admin/frames" className={styles.manage}>
          Manage all frames
        </Link>
      </div>
      <p className={styles.summary} aria-live="polite" data-testid="available-frames-summary">
        {count === 1 ? '1 frame available to participants' : `${count} frames available to participants`}
      </p>
      <p className={styles.helper}>
        Participants choose their frame at the booth; its size decides how many photos are taken.
      </p>

      {count === 0 && frames !== undefined && (
        <div role="alert" className={styles.alert}>
          No frames are available to participants. Turn at least one frame on; an event without
          frames can not be activated.
        </div>
      )}
      {frames === undefined && !loadFailed && <p className={styles.helper}>Loading frames…</p>}
      {loadFailed && frames === undefined && (
        <div role="alert" className={styles.alert}>
          <p>The frames could not be loaded, so they can not be changed right now. Saving keeps the current list.</p>
          <button type="button" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}

      <div className={styles.tools}>
        <label className={styles.search}>
          <span>Search frames</span>
          <input
            type="search"
            value={query}
            placeholder="e.g. Gold"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className={styles.tabs} role="group" aria-label="Show frames of">
          {[{ key: ALL, label: 'All' }, ...templates.map((t) => ({ key: t.key, label: layoutLabel(t) }))].map(
            (item) => (
              <button
                key={item.key}
                type="button"
                aria-pressed={tab === item.key}
                className={styles.tab}
                onClick={() => setTab(item.key)}
              >
                {item.label}
              </button>
            ),
          )}
        </div>
        <div className={styles.bulk}>
          {layoutKeys.map((key) => (
            <span key={key} className={styles.bulkGroup}>
              <button type="button" disabled={locked} onClick={() => setLayout(key, true)}>
                Enable all {labelOf(key)}
              </button>
              <button type="button" disabled={locked} onClick={() => setLayout(key, false)}>
                Disable all {labelOf(key)}
              </button>
            </span>
          ))}
        </div>
      </div>

      <h3 className={styles.listHeading}>Shown to participants, in this order</h3>
      {enabledShown.length === 0 ? (
        <p className={styles.helper}>None {count > 0 ? 'match this search' : 'yet'}.</p>
      ) : (
        <ol className={styles.list} aria-label="Frames shown to participants">
          {enabledShown.map((frame, index) => row(frame, true, index))}
        </ol>
      )}

      {frames !== undefined && (
        <>
          <h3 className={styles.listHeading}>Not shown</h3>
          {others.length === 0 ? (
            <p className={styles.helper}>Every matching frame is shown.</p>
          ) : (
            <ul className={styles.list} aria-label="Frames not shown">
              {others.map((frame, index) => row(frame, false, index))}
            </ul>
          )}
        </>
      )}

      <label className={styles.surprise}>
        <input
          type="checkbox"
          checked={allowSurprise}
          disabled={disabled}
          onChange={(e) => onSurpriseChange(e.target.checked)}
          aria-describedby="help-surprise"
        />
        Allow “Surprise me” random frame
      </label>
      <p id="help-surprise" className={styles.helper}>
        Shown to participants only when at least two frames are available; it picks one of them.
      </p>
    </section>
  )
}
