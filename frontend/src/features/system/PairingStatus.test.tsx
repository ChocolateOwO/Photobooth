import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { App } from '../../app/App'
import { createApiClient } from '../../shared/api/client'
import type { DeviceKeyStore } from '../../shared/api/deviceKey'
import { PairingStatus } from './PairingStatus'

function store(key: string | null): DeviceKeyStore {
  return { get: () => key, set: () => undefined, clear: () => undefined }
}

function renderStatus(paired: boolean, key: string | null) {
  const api = createApiClient(
    async () =>
      new Response(JSON.stringify({ paired }), { headers: { 'Content-Type': 'application/json' } }),
    store(key),
  )
  render(
    <App instance="dummy" apiClient={api}>
      <PairingStatus />
    </App>,
  )
}

describe('PairingStatus', () => {
  it('reports a paired kiosk only when the browser holds the device key', async () => {
    renderStatus(true, 'k'.repeat(43))
    expect(await screen.findByText('Kiosk paired')).toBeInTheDocument()
  })

  it('asks for re-pairing when the cookie is valid but the device key is missing', async () => {
    renderStatus(true, null)
    expect(await screen.findByText(/needs re-pairing/)).toBeInTheDocument()
  })

  it('explains how to pair when not paired', async () => {
    renderStatus(false, null)
    expect(await screen.findByText(/Kiosk not paired/)).toBeInTheDocument()
  })
})
