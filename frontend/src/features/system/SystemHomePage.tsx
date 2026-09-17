import { Link } from 'react-router'

import type { InstanceName } from '../../shared/config/instance'
import { HealthStatus } from './HealthStatus'
import { PairingStatus } from './PairingStatus'

/** Phase 1 shell page. Product screens arrive in later phases. */
export function SystemHomePage({ instance }: { instance: InstanceName }) {
  return (
    <main style={{ maxWidth: 720, margin: '0 auto', padding: '96px 24px 24px' }}>
      <h1>Photobooth</h1>
      <p>Foundation shell. No product features yet.</p>
      <HealthStatus expectedInstance={instance} />
      <PairingStatus />
      <p style={{ marginTop: 'var(--pb-space)' }}>
        <Link
          to="/admin"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: 'var(--pb-touch-target)',
            padding: '0 24px',
            borderRadius: 'var(--pb-radius)',
            backgroundColor: 'var(--pb-color-surface)',
            color: 'var(--pb-color-text)',
            textDecoration: 'none',
            fontWeight: 600,
          }}
        >
          Admin
        </Link>
      </p>
    </main>
  )
}

