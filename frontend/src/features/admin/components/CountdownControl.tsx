import { useState, type KeyboardEvent } from 'react'

import { COUNTDOWN_LIMITS } from '../../../shared/api/adminClient'
import { Icon } from './ui/Icon'
import styles from './CountdownControl.module.css'

interface CountdownControlProps {
  id: string
  /** Whole seconds; NaN while the typed text is not a whole number. */
  value: number
  onChange: (seconds: number) => void
  disabled: boolean
  /** aria-invalid / aria-describedby / data-invalid from the form's validation. */
  fieldProps?: Record<string, string | boolean | undefined>
}

function parse(text: string): number {
  return /^\s*\d+\s*$/.test(text) ? Number(text) : Number.NaN
}

/**
 * The seconds counted down before each photo: a small number field with Up and Down arrows
 * (also the keyboard arrow keys). Values outside 1-10 or not whole are reported on save.
 */
export function CountdownControl({ id, value, onChange, disabled, fieldProps }: CountdownControlProps) {
  const [draft, setDraft] = useState(Number.isNaN(value) ? '' : String(value))
  const [shown, setShown] = useState(value)
  if (!Object.is(shown, value)) {
    setShown(value)
    // Changed elsewhere (reload latest): show the new value. Typing keeps its own text, even when
    // that text is not a whole number yet ("2." on the way to something else).
    if (!Object.is(parse(draft), value)) setDraft(Number.isNaN(value) ? '' : String(value))
  }
  const valid = Number.isInteger(value)
  const base = valid ? value : COUNTDOWN_LIMITS.default
  const step = (delta: 1 | -1) => {
    const next = Math.min(COUNTDOWN_LIMITS.max, Math.max(COUNTDOWN_LIMITS.min, base + delta))
    setDraft(String(next))
    onChange(next)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()
      step(e.key === 'ArrowUp' ? 1 : -1)
    }
  }

  return (
    <div className={styles.control}>
      <input
        id={id}
        type="text"
        inputMode="numeric"
        role="spinbutton"
        aria-valuemin={COUNTDOWN_LIMITS.min}
        aria-valuemax={COUNTDOWN_LIMITS.max}
        {...(valid ? { 'aria-valuenow': value, 'aria-valuetext': `${value} seconds` } : {})}
        value={draft}
        maxLength={3}
        disabled={disabled}
        onChange={(e) => {
          setDraft(e.target.value)
          onChange(parse(e.target.value))
        }}
        onKeyDown={onKeyDown}
        className={styles.number}
        {...fieldProps}
      />
      <span className={styles.unit} aria-hidden="true">
        seconds
      </span>
      <span className={styles.arrows}>
        <button
          type="button"
          className={styles.arrow}
          aria-label="Increase countdown"
          title="Increase countdown"
          disabled={disabled || (valid && value >= COUNTDOWN_LIMITS.max)}
          onClick={() => step(1)}
        >
          <Icon name="up" size={18} />
        </button>
        <button
          type="button"
          className={styles.arrow}
          aria-label="Decrease countdown"
          title="Decrease countdown"
          disabled={disabled || (valid && value <= COUNTDOWN_LIMITS.min)}
          onClick={() => step(-1)}
        >
          <Icon name="down" size={18} />
        </button>
      </span>
    </div>
  )
}
