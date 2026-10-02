import { Component, useEffect, type ErrorInfo, type ReactNode } from 'react'

import styles from './BoothSafety.module.css'

/**
 * What a guest sees when something goes wrong at the booth, instead of a blank screen.
 *
 * - Reconnecting: the booth can not reach its own server for a moment. It covers the screen
 *   (so nothing half-works underneath) and goes away by itself when the server answers again.
 * - Start again: a screen failed in a way it could not handle. One tap, or a short wait, starts
 *   the booth again from its start screen.
 */

export function Reconnecting() {
  return (
    <div className={styles.overlay} role="status" aria-live="polite" data-testid="booth-offline">
      <div className={styles.card}>
        <span className={styles.spinner} aria-hidden="true" />
        <p className={styles.title}>One moment…</p>
        <p className={styles.text}>The booth is reconnecting. Please wait.</p>
      </div>
    </div>
  )
}

/** After this long on the error screen, the booth starts again by itself. */
const RESTART_AFTER_MS = 30_000

function StartAgain({ onRestart }: { onRestart: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onRestart, RESTART_AFTER_MS)
    return () => window.clearTimeout(timer)
  }, [onRestart])
  return (
    <div className={styles.overlay} role="alert" data-testid="booth-crashed">
      <div className={styles.card}>
        <p className={styles.title}>Sorry, something went wrong.</p>
        <p className={styles.text}>Your photos are safe on the booth.</p>
        <button type="button" className={styles.button} onClick={onRestart}>
          Start again
        </button>
      </div>
    </div>
  )
}

interface BoundaryProps {
  children: ReactNode
  /** How the booth starts again; the real booth reloads its start screen. */
  onRestart?: () => void
}

/** Catches any error a booth screen throws while drawing, so the booth never goes blank. */
export class BoothErrorBoundary extends Component<BoundaryProps, { failed: boolean }> {
  override state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // The console only: no screen content, no visit data.
    console.error('booth screen failed', error.name, info.componentStack?.split('\n')[1]?.trim())
  }

  private restart = () => {
    if (this.props.onRestart) {
      this.setState({ failed: false })
      this.props.onRestart()
      return
    }
    window.location.assign('/booth')
  }

  override render(): ReactNode {
    if (this.state.failed) return <StartAgain onRestart={this.restart} />
    return this.props.children
  }
}
