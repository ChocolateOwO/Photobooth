import type { InstanceName } from '../config/instance'
import { useImmersive } from './immersive'
import styles from './DummyBadge.module.css'

/** Always-visible marker so a Dummy screen can never be mistaken for Main. */
export function DummyBadge({ instance }: { instance: InstanceName }) {
  // A booth screen is the participant's whole display; the badge comes back the moment it ends.
  const immersive = useImmersive()
  if (instance !== 'dummy' || immersive) {
    return null
  }
  return (
    <div className={styles.badge} aria-label="DUMMY instance" data-testid="dummy-badge">
      DUMMY
    </div>
  )
}
