import type { InstanceName } from '../../shared/config/instance'
import { BigButton } from '../../shared/ui/BigButton'
import styles from './HealthStatus.module.css'
import { useHealth } from './useSystemStatus'

type View = { message: string; tone: 'ok' | 'error' | 'muted' }

/** "API OK" only when the API is healthy AND belongs to the same instance as this UI build. */
export function HealthStatus({ expectedInstance }: { expectedInstance: InstanceName }) {
  const { data, isPending, isError, isFetching, refetch } = useHealth()

  let view: View
  if (isPending) {
    view = { message: 'Checking API…', tone: 'muted' }
  } else if (isError || data.status !== 'ok') {
    view = { message: 'API ERROR', tone: 'error' }
  } else if (data.instance !== expectedInstance) {
    view = {
      message: `INSTANCE MISMATCH: UI is ${expectedInstance}, API is ${data.instance}`,
      tone: 'error',
    }
  } else {
    view = { message: 'API OK', tone: 'ok' }
  }

  return (
    <section className={styles.panel} aria-labelledby="health-heading">
      <h2 id="health-heading">System status</h2>
      <p className={styles[view.tone]} role="status" data-testid="health-status">
        {view.message}
      </p>
      <BigButton onClick={() => void refetch()} disabled={isFetching}>
        Check again
      </BigButton>
    </section>
  )
}
