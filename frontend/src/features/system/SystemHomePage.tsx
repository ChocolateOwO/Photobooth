import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { useApiClient } from '../../shared/api/ApiClientContext'
import type { InstanceName } from '../../shared/config/instance'
import { HealthStatus } from './HealthStatus'
import { PairingStatus } from './PairingStatus'

/**
 * The machine's own start page (`/`): is the booth's server well, which version runs, is this
 * browser paired as the kiosk, and the two ways on: the booth for guests, Admin for organizers.
 * Nothing here is for guests and nothing here is secret.
 */

const linkStyle = {
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
} as const

function Version() {
  const api = useApiClient()
  const version = useQuery({ queryKey: ['system', 'version'], queryFn: api.version, retry: false })
  if (!version.data) return null
  const v = version.data
  return (
    <p data-testid="version" style={{ color: 'var(--pb-color-muted)' }}>
      Version {v.app_version} · API {v.api_version} · {v.instance} · database{' '}
      {v.schema_revision ?? 'unknown'} · code {v.git_commit ? v.git_commit.slice(0, 12) : 'unknown'}
    </p>
  )
}

export function SystemHomePage({ instance }: { instance: InstanceName }) {
  return (
    <main style={{ maxWidth: 720, margin: '0 auto', padding: '96px 24px 24px' }}>
      <h1>Photobooth</h1>
      <p>This machine runs the photo booth. Guests use the booth screen; organizers use Admin.</p>
      <Version />
      <HealthStatus expectedInstance={instance} />
      <PairingStatus />
      <p style={{ marginTop: 'var(--pb-space)', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <Link to="/booth" style={linkStyle}>
          Open the booth
        </Link>
        <Link to="/admin" style={linkStyle}>
          Admin
        </Link>
      </p>
    </main>
  )
}
