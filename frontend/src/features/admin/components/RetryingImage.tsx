import { useEffect, useState } from 'react'

import styles from './RetryingImage.module.css'

/** Automatic retries after a failed load (the render queue answers 503 while it is full). */
const AUTO_RETRY_DELAYS_MS = [1000, 2000, 4000] as const

interface RetryingImageProps {
  src: string
  alt: string
  className?: string | undefined
}

interface LoadState {
  src: string
  attempt: number
  autoRetriesUsed: number
  phase: 'loading' | 'waiting' | 'failed'
}

function initial(src: string): LoadState {
  return { src, attempt: 0, autoRetriesUsed: 0, phase: 'loading' }
}

function attemptUrl(src: string, attempt: number): string {
  if (attempt === 0) return src
  return `${src}${src.includes('?') ? '&' : '?'}retry=${attempt}`
}

/**
 * A lazily loaded server image (rendered frame previews) that retries with a growing delay and
 * then offers a visible Retry button, instead of leaving a broken image behind.
 */
export function RetryingImage({ src, alt, className }: RetryingImageProps) {
  const [state, setState] = useState<LoadState>(() => initial(src))
  // A new source (for example a replaced frame file) starts over.
  const current = state.src === src ? state : initial(src)
  if (current !== state) {
    setState(current)
  }

  useEffect(() => {
    if (current.phase !== 'waiting') return undefined
    const delay = AUTO_RETRY_DELAYS_MS[current.autoRetriesUsed - 1] ?? 4000
    const timer = window.setTimeout(() => {
      setState((s) => (s.phase === 'waiting' ? { ...s, attempt: s.attempt + 1, phase: 'loading' } : s))
    }, delay)
    return () => window.clearTimeout(timer)
  }, [current.phase, current.autoRetriesUsed])

  const handleError = () => {
    setState((s) =>
      s.autoRetriesUsed < AUTO_RETRY_DELAYS_MS.length
        ? { ...s, autoRetriesUsed: s.autoRetriesUsed + 1, phase: 'waiting' }
        : { ...s, phase: 'failed' },
    )
  }

  const handleManualRetry = () => {
    setState((s) => ({ ...s, attempt: s.attempt + 1, autoRetriesUsed: 0, phase: 'loading' }))
  }

  return (
    <>
      <img
        key={current.attempt}
        src={attemptUrl(current.src, current.attempt)}
        alt={alt}
        loading="lazy"
        decoding="async"
        className={className}
        hidden={current.phase !== 'loading'}
        onError={handleError}
      />
      {current.phase === 'waiting' && (
        <p className={styles.notice}>Preparing the preview…</p>
      )}
      {current.phase === 'failed' && (
        <div className={styles.failed}>
          <p className={styles.notice}>The preview could not be loaded. The booth may be busy.</p>
          <button type="button" onClick={handleManualRetry} aria-label={`Retry ${alt}`}>
            Retry
          </button>
        </div>
      )}
    </>
  )
}
