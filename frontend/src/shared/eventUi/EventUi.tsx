import type { AnchorHTMLAttributes, ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'

import { themeStyle, type ThemeTokens } from '../eventTheme/theme'
import styles from './EventUi.module.css'

/**
 * Event-facing building blocks (kiosk screens and their admin preview). Every colour comes from
 * the event theme tokens (`--ev-*`); nothing here has a hard-coded colour.
 */

function cx(...names: (string | false | undefined)[]): string {
  return names.filter(Boolean).join(' ')
}

interface EventScreenProps {
  tokens: ThemeTokens
  backgroundImageUrl?: string | null
  className?: string | undefined
  children: ReactNode
  label?: string
}

/** Applies the theme to everything inside it (and nothing outside). */
export function EventScreen({ tokens, backgroundImageUrl, className, children, label }: EventScreenProps) {
  return (
    <div
      className={cx(styles.screen, className)}
      style={{
        ...themeStyle(tokens),
        ...(backgroundImageUrl
          ? { backgroundImage: `url("${backgroundImageUrl}")` }
          : {}),
      }}
      data-event-theme=""
      {...(label ? { role: 'group', 'aria-label': label } : {})}
    >
      {children}
    </div>
  )
}

export function EventHeading({ children, level = 2 }: { children: ReactNode; level?: 1 | 2 | 3 }) {
  const Tag = `h${level}` as const
  return <Tag className={styles.heading}>{children}</Tag>
}

export function EventText({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  return <p className={muted ? styles.muted : styles.body}>{children}</p>
}

export function EventLink(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a {...props} className={cx(styles.link, props.className)} />
}

type Variant = 'primary' | 'secondary' | 'danger'

interface EventButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  /** Previews only: show the hover or pressed colours without a pointer. */
  demoState?: 'hover' | 'pressed' | undefined
}

export function EventButton({ variant = 'primary', demoState, className, ...rest }: EventButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      data-demo-state={demoState}
      className={cx(styles.button, styles[variant], className)}
    />
  )
}

interface EventInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  /** Previews only: show the active (focused) border. */
  demoFocus?: boolean
}

export function EventInput({ label, demoFocus = false, id, className, ...rest }: EventInputProps) {
  return (
    <label className={styles.field} htmlFor={id}>
      <span className={styles.fieldLabel}>{label}</span>
      <input
        id={id}
        {...rest}
        data-demo-focus={demoFocus ? '' : undefined}
        className={cx(styles.input, className)}
      />
    </label>
  )
}

export function EventCard({
  children,
  className,
}: {
  children: ReactNode
  className?: string | undefined
}) {
  return <div className={cx(styles.card, className)}>{children}</div>
}

export type MessageKind = 'success' | 'warning' | 'error' | 'info'

export function EventMessage({ kind, children }: { kind: MessageKind; children: ReactNode }) {
  return (
    <div className={cx(styles.message, styles[kind])} data-kind={kind}>
      {children}
    </div>
  )
}

/** A dialog on the dimmed backdrop (overlay token), shown inline in previews. */
export function EventDialog({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className={styles.backdrop}>
      <div className={styles.dialog} role="dialog" aria-label={title} aria-modal="false">
        <p className={styles.dialogTitle}>{title}</p>
        {children}
      </div>
    </div>
  )
}
