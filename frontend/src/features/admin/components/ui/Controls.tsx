import { useRef, type ButtonHTMLAttributes, type KeyboardEvent, type ReactNode } from 'react'

import { Icon, type IconName } from './Icon'
import styles from './Controls.module.css'

export interface PillOption {
  value: string
  label: string
}

interface PillGroupProps {
  /** Accessible name of the group, for example "Show frames of". */
  label: string
  options: PillOption[]
  value: string
  onChange: (value: string) => void
  className?: string | undefined
}

/**
 * A single-choice segmented pill control. One pill is in the Tab order (the selected one);
 * arrow keys, Home and End move the choice, Enter and Space press the focused pill.
 */
export function PillGroup({ label, options, value, onChange, className }: PillGroupProps) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const selectedIndex = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  )

  const moveTo = (index: number) => {
    const count = options.length
    const next = (index + count) % count
    const option = options[next]
    if (!option) return
    onChange(option.value)
    const button = refs.current[next]
    button?.focus()
    button?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const keys: Record<string, () => void> = {
      ArrowRight: () => moveTo(index + 1),
      ArrowDown: () => moveTo(index + 1),
      ArrowLeft: () => moveTo(index - 1),
      ArrowUp: () => moveTo(index - 1),
      Home: () => moveTo(0),
      End: () => moveTo(options.length - 1),
    }
    const action = keys[e.key]
    if (action) {
      e.preventDefault()
      action()
    }
  }

  return (
    <div
      role="group"
      aria-label={label}
      className={className ? `${styles.pillRow} ${className}` : styles.pillRow}
      data-pill-group=""
    >
      {options.map((option, index) => {
        const selected = index === selectedIndex
        return (
          <button
            key={option.value}
            ref={(el) => {
              refs.current[index] = el
            }}
            type="button"
            aria-pressed={selected}
            tabIndex={selected ? 0 : -1}
            className={styles.pill}
            onClick={() => onChange(option.value)}
            onKeyDown={(e) => onKeyDown(e, index)}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

interface PillButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: 'plain' | 'primary' | 'danger'
  icon?: IconName
}

export function PillButton({ tone = 'plain', icon, className, children, ...rest }: PillButtonProps) {
  const toneClass = tone === 'primary' ? styles.pillPrimary : tone === 'danger' ? styles.pillDanger : ''
  return (
    <button
      type="button"
      {...rest}
      className={[styles.pill, toneClass, className].filter(Boolean).join(' ')}
    >
      {icon && <Icon name={icon} size={18} />}
      {children}
    </button>
  )
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName
  /** Accessible name; also shown as a tooltip. */
  label: string
  danger?: boolean
}

export function IconButton({ icon, label, danger = false, className, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...rest}
      className={[styles.iconButton, danger ? styles.iconDanger : '', className].filter(Boolean).join(' ')}
    >
      <Icon name={icon} />
    </button>
  )
}

interface SwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  /** Accessible name when the visible text is not enough (for example "Show Gold (2×6) to participants"). */
  ariaLabel?: string
  /** Visible text next to the switch; defaults to On / Off. */
  children?: ReactNode
  describedBy?: string
  className?: string | undefined
}

/** A sliding on/off switch: a native checkbox with role="switch", so the whole label toggles it. */
export function Switch({
  checked,
  onChange,
  disabled = false,
  ariaLabel,
  children,
  describedBy,
  className,
}: SwitchProps) {
  return (
    <label
      className={className ? `${styles.switch} ${className}` : styles.switch}
      data-disabled={disabled ? '' : undefined}
    >
      <input
        type="checkbox"
        role="switch"
        className={styles.switchInput}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        {...(ariaLabel ? { 'aria-label': ariaLabel } : {})}
        {...(describedBy ? { 'aria-describedby': describedBy } : {})}
      />
      <span className={styles.track} aria-hidden="true">
        <span className={styles.thumb} />
      </span>
      <span className={styles.switchText} aria-hidden={ariaLabel ? true : undefined}>
        {children ?? (checked ? 'On' : 'Off')}
      </span>
    </label>
  )
}
