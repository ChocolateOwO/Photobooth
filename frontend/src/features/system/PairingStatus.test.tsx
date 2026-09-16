import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { App } from '../../app/App'
import { createApiClient } from '../../shared/api/client'
import { PairingStatus } from './PairingStatus'

function renderPaired(paired: boolean) {
  const api = createApiClient(
    async () =>
      new Response(JSON.stringify({ paired }), { headers: { 'Content-Type': 'application/json' } }),
  )
  render(
    <App instance="dummy" apiClient={api}>
      <PairingStatus />
    </App>,
  )
}

describe('PairingStatus', () => {
  it('reports a paired kiosk', async () => {
    renderPaired(true)
    expect(await screen.findByText('Kiosk paired')).toBeInTheDocument()
  })

  it('explains how to pair when not paired', async () => {
    renderPaired(false)
    expect(await screen.findByText(/Kiosk not paired/)).toBeInTheDocument()
  })
})
