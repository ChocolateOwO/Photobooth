import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'

import { Icon, type IconName } from './Icon'
import styles from './Modal.module.css'

/** Open dialogs, newest last: only the top one reacts to Escape and Tab. */
const openDialogs: HTMLElement[] = []

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export interface ModalProps {
  title: string
  onClose: () => void
  children: ReactNode
  role?: 'dialog' | 'alertdialog'
  size?: 'small' | 'medium' | 'large'
  /** Escape, the backdrop and the corner Close button close it. */
  dismissible?: boolean
  /** Show the corner Close (x) button when dismissible. */
  showCloseButton?: boolean
  icon?: IconName
  tone?: 'plain' | 'success' | 'warning' | 'error'
  footer?: ReactNode
  initialFocus?: RefObject<HTMLElement | null>
  /** Return focus to the control that opened the dialog when it closes (default). */
  restoreFocus?: boolean
  testId?: string
}

/**
 * A centred modal dialog on a dimmed backdrop, rendered at the end of the page so it never
 * moves the layout. Focus moves in, is trapped while open and goes back to the opener.
 */
export function Modal({
  title,
  onClose,
  children,
  role = 'dialog',
  size = 'medium',
  dismissible = true,
  showCloseButton = true,
  icon,
  tone = 'plain',
  footer,
  initialFocus,
  restoreFocus = true,
  testId,
}: ModalProps) {
  const titleId = useId()
  const bodyId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const restoreRef = useRef(restoreFocus)
  useEffect(() => {
    restoreRef.current = restoreFocus
  }, [restoreFocus])

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current
    const target =
      initialFocus?.current ??
      dialog?.querySelector<HTMLElement>('[data-autofocus]') ??
      dialog?.querySelector<HTMLElement>(FOCUSABLE) ??
      dialog
    target?.focus({ preventScroll: true })
    return () => {
      if (restoreRef.current && opener?.isConnected) opener.focus({ preventScroll: true })
    }
    // Focus is placed once, when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Keys are handled on the document, so they still work when focus was lost (for example to a
  // button that became disabled while a request runs).
  const closeRef = useRef(onClose)
  const dismissibleRef = useRef(dismissible)
  useEffect(() => {
    closeRef.current = onClose
    dismissibleRef.current = dismissible
  }, [onClose, dismissible])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return undefined
    openDialogs.push(dialog)
    const onKeyDown = (e: KeyboardEvent) => {
      if (openDialogs[openDialogs.length - 1] !== dialog) return
      if (e.key === 'Escape') {
        e.preventDefault()
        if (dismissibleRef.current) closeRef.current()
        return
      }
      if (e.key !== 'Tab') return
      const items = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)]
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (!first || !last) {
        e.preventDefault()
        dialog.focus()
      } else if (!dialog.contains(active)) {
        e.preventDefault()
        ;(e.shiftKey ? last : first).focus()
      } else if (e.shiftKey && active === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      openDialogs.splice(openDialogs.indexOf(dialog), 1)
    }
  }, [])
  return createPortal(
    <div
      className={styles.backdrop}
      onMouseDown={(e) => {
        if (dismissible && e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={dialogRef}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        className={`${styles.dialog} ${styles[size]}`}
        data-tone={tone}
        data-testid={testId}
      >
        <div className={styles.header}>
          {icon && (
            <span className={styles.icon}>
              <Icon name={icon} size={28} />
            </span>
          )}
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
          {dismissible && showCloseButton && (
            <button type="button" className={styles.close} onClick={onClose} aria-label="Close">
              <Icon name="close" />
            </button>
          )}
        </div>
        <div id={bodyId} className={styles.body}>
          {children}
        </div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
