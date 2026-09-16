import type { InstanceName } from '../config/instance'
import styles from './DummyBadge.module.css'

/** Always-visible marker so a Dummy screen can never be mistaken for Main. */
export function DummyBadge({ instance }: { instance: InstanceName }) {
  if (instance !== 'dummy') {
    return null
  }
  return (
    <div className={styles.badge} aria-label="DUMMY instance" data-testid="dummy-badge">
      DUMMY
    </div>
  )
}
