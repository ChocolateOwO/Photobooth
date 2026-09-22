import { useEffect, useRef, type ReactNode } from 'react'

import { PillButton } from './Controls'
import { Modal } from './Modal'

export type MessageKind = 'success' | 'warning' | 'error' | 'confirm'

interface MessageDialogProps {
  kind: MessageKind
  title: string
  children: ReactNode
  onClose: () => void
  /** Extra actions before the closing button (for example "Reload latest" or "Delete frame"). */
  actions?: ReactNode
  /** Label of the closing button (for a confirmation: "Cancel"). */
  closeLabel?: string
  /** Success messages may close by themselves after this many milliseconds. */
  autoCloseMs?: number
  restoreFocus?: boolean
  testId?: string
}

const ICONS = { success: 'success', warning: 'warning', error: 'error', confirm: 'warning' } as const
const TONES = { success: 'success', warning: 'warning', error: 'error', confirm: 'warning' } as const

/**
 * The centred pop-up for results: saved, missing information, failures, conflicts and
 * destructive confirmations. Announced by screen readers as an alert dialog. Escape closes it
 * (for a confirmation that means Cancel, never the destructive action).
 */
export function MessageDialog({
  kind,
  title,
  children,
  onClose,
  actions,
  closeLabel = kind === 'confirm' ? 'Cancel' : 'Close',
  autoCloseMs,
  restoreFocus = true,
  testId,
}: MessageDialogProps) {
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])
  useEffect(() => {
    if (!autoCloseMs) return undefined
    const timer = window.setTimeout(() => closeRef.current(), autoCloseMs)
    return () => window.clearTimeout(timer)
  }, [autoCloseMs])

  // A confirmation starts on Cancel; other messages start on their first action.
  const focusClose = kind === 'confirm' || !actions
  return (
    <Modal
      title={title}
      onClose={onClose}
      role="alertdialog"
      size="small"
      icon={ICONS[kind]}
      tone={TONES[kind]}
      showCloseButton={false}
      restoreFocus={restoreFocus}
      {...(testId ? { testId } : {})}
      footer={
        <>
          {actions}
          <PillButton onClick={onClose} {...(focusClose ? { 'data-autofocus': '' } : {})}>
            {closeLabel}
          </PillButton>
        </>
      }
    >
      {children}
    </Modal>
  )
}
