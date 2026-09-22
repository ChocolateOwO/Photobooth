import { ApiError } from '../../shared/api/client'
import styles from './FrameSelectPage.module.css'

interface BoothLoadStateProps {
  error: unknown
  onRetry: () => void
}

/** Why a participant screen can not show the event yet (no active event, not paired, failed). */
export function BoothLoadState({ error, onRetry }: BoothLoadStateProps) {
  const noEvent = error instanceof ApiError && error.status === 404
  const notPaired = error instanceof ApiError && error.status === 401
  return (
    <div className={styles.plain} role="alert">
      <p>
        {noEvent
          ? 'This booth has no active event yet. Ask the organizer to activate an Event Profile.'
          : notPaired
            ? 'This screen is not paired with the booth.'
            : 'The event could not be loaded.'}
      </p>
      <button type="button" className={styles.retry} onClick={onRetry}>
        Try again
      </button>
    </div>
  )
}
