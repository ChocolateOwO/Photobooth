import { Link } from 'react-router'

import type { Frame, TemplateSummary } from '../../../shared/api/adminClient'
import { framesForSizes, layoutLabel } from '../frameCatalog'
import controls from './ui/Controls.module.css'
import styles from './PhotoSizesSelector.module.css'

interface PhotoSizesSelectorProps {
  templates: TemplateSummary[]
  /** The frame library, for the counts (undefined while it loads or when it failed). */
  frames: Frame[] | undefined
  /** Chosen photo sizes (layout keys). */
  value: string[]
  onChange: (layouts: string[]) => void
  disabled: boolean
  /** The frame list failed: counts are unknown until the admin retries. */
  loadFailed: boolean
  onRetry: () => void
}

/**
 * Which photo sizes participants may use. Every valid frame of a chosen size is offered at the
 * booth, including frames uploaded later; the frames themselves are managed on the Frames page.
 */
export function PhotoSizesSelector({
  templates,
  frames,
  value,
  onChange,
  disabled,
  loadFailed,
  onRetry,
}: PhotoSizesSelectorProps) {
  const toggle = (key: string) => {
    const chosen = value.includes(key) ? value.filter((k) => k !== key) : [...value, key]
    // Kept in the template order (the order participants see).
    onChange(templates.map((t) => t.key).filter((k) => chosen.includes(k)))
  }
  const offered = frames ? framesForSizes(value, frames, templates).length : null

  return (
    <section className={styles.section} aria-labelledby="photo-sizes-heading">
      <div className={styles.header}>
        <h2 id="photo-sizes-heading" className={styles.heading}>
          Photo sizes available
        </h2>
        <Link to="/admin/frames" className={styles.manage}>
          Manage all frames
        </Link>
      </div>
      <div className={styles.pills} role="group" aria-label="Photo sizes available">
        {templates.map((template) => {
          const on = value.includes(template.key)
          const count = frames ? framesForSizes([template.key], frames, templates).length : null
          const label = layoutLabel(template)
          return (
            <button
              key={template.key}
              type="button"
              className={controls.pill}
              aria-pressed={on}
              disabled={disabled}
              onClick={() => toggle(template.key)}
              aria-label={count === null ? label : `${label}, ${count} ${count === 1 ? 'frame' : 'frames'}`}
              data-testid="photo-size"
            >
              {label}
              {count !== null && (
                <span className={styles.count} aria-hidden="true">
                  {` · ${count} ${count === 1 ? 'frame' : 'frames'}`}
                </span>
              )}
            </button>
          )
        })}
      </div>
      <p className={styles.helper}>
        Participants choose any frame of these sizes at the booth. Frames added later appear
        automatically.
        {offered !== null && (
          <span className={styles.summary} data-testid="available-frames-summary" aria-live="polite">
            {' '}
            {offered === 1 ? '1 frame available to participants.' : `${offered} frames available to participants.`}
          </span>
        )}
      </p>
      {loadFailed && frames === undefined && (
        <div role="alert" className={styles.alert}>
          <p className={styles.alertText}>
            The frames could not be loaded, so their counts are not shown. The chosen sizes are
            still saved.
          </p>
          <button type="button" className={controls.pill} onClick={onRetry}>
            Try again
          </button>
        </div>
      )}
      {value.length === 0 && (
        <div role="alert" className={styles.alert}>
          No photo size is chosen. Choose at least one; a profile without photo sizes can not be
          activated.
        </div>
      )}
    </section>
  )
}
