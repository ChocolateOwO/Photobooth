import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { MessageDialog } from './MessageDialog'
import { Modal } from './Modal'

function Opener({ children }: { children: (close: () => void) => React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      {open && children(() => setOpen(false))}
    </>
  )
}

describe('Modal', () => {
  it('traps focus, closes on Escape and returns focus to the opener', async () => {
    render(
      <Opener>
        {(close) => (
          <Modal title="Details" onClose={close} footer={<button type="button">Last</button>}>
            <button type="button">First inside</button>
          </Modal>
        )}
      </Opener>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    const dialog = screen.getByRole('dialog', { name: 'Details' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    const close = screen.getByRole('button', { name: 'Close' })
    expect(close).toHaveFocus() // the first control
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'First inside' })).toHaveFocus()
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Last' })).toHaveFocus()
    await userEvent.tab() // wraps around, never leaves the dialog
    expect(close).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Last' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: 'Open' })).toHaveFocus()
  })

  it('a non-dismissible dialog ignores Escape', async () => {
    const onClose = vi.fn()
    render(
      <Modal title="Busy" onClose={onClose} dismissible={false}>
        <button type="button">Only</button>
      </Modal>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull()
  })
})

describe('MessageDialog', () => {
  it('is announced as an alert dialog and a success closes by itself', () => {
    vi.useFakeTimers()
    try {
      const onClose = vi.fn()
      render(
        <MessageDialog kind="success" title="Saved" autoCloseMs={2500} onClose={onClose}>
          <p>Profile saved successfully.</p>
        </MessageDialog>,
      )
      const dialog = screen.getByRole('alertdialog', { name: 'Saved' })
      expect(dialog).toHaveAccessibleDescription('Profile saved successfully.')
      expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
      act(() => {
        vi.advanceTimersByTime(2500)
      })
      expect(onClose).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('a confirmation starts on Cancel and Escape cancels, never confirms', async () => {
    const onClose = vi.fn()
    const onDelete = vi.fn()
    render(
      <MessageDialog
        kind="confirm"
        title="Delete Gold?"
        onClose={onClose}
        actions={
          <button type="button" onClick={onDelete}>
            Delete frame
          </button>
        }
      >
        <p>It is removed.</p>
      </MessageDialog>,
    )
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onDelete).not.toHaveBeenCalled()
  })
})
