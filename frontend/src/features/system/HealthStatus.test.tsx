import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { ApiError, createApiClient, type Fetcher } from '../../shared/api/client'
import { HealthStatus } from './HealthStatus'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderWith(fetcher: Fetcher, expected: 'dummy' | 'main' = 'dummy') {
  return render(
    <App instance={expected} apiClient={createApiClient(fetcher)}>
      <HealthStatus expectedInstance={expected} />
    </App>,
  )
}

describe('HealthStatus', () => {
  it('shows API OK for a healthy API of the same instance', async () => {
    const fetcher = vi.fn<Fetcher>(async () =>
      jsonResponse({ status: 'ok', instance: 'dummy', database: 'ok' }),
    )
    renderWith(fetcher)
    expect(await screen.findByText('API OK')).toBeInTheDocument()
    expect(fetcher).toHaveBeenCalledWith('/api/health', expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('shows API ERROR when the request fails', async () => {
    renderWith(async () => jsonResponse({ detail: 'down' }, 503))
    expect(await screen.findByText('API ERROR')).toBeInTheDocument()
  })

  it('shows API ERROR when the network rejects', async () => {
    renderWith(async () => {
      throw new TypeError('Failed to fetch')
    })
    expect(await screen.findByText('API ERROR')).toBeInTheDocument()
  })

  it('shows API ERROR when database is down', async () => {
    renderWith(async () => jsonResponse({ status: 'error', instance: 'dummy', database: 'error' }))
    expect(await screen.findByText('API ERROR')).toBeInTheDocument()
  })

  it('refuses to show OK when the API belongs to another instance', async () => {
    renderWith(async () => jsonResponse({ status: 'ok', instance: 'main', database: 'ok' }))
    expect(
      await screen.findByText('INSTANCE MISMATCH: UI is dummy, API is main'),
    ).toBeInTheDocument()
    expect(screen.queryByText('API OK')).not.toBeInTheDocument()
  })

  it('re-checks when the large button is pressed', async () => {
    let healthy = false
    renderWith(async () =>
      healthy
        ? jsonResponse({ status: 'ok', instance: 'dummy', database: 'ok' })
        : jsonResponse({}, 500),
    )
    expect(await screen.findByText('API ERROR')).toBeInTheDocument()
    healthy = true
    const button = screen.getByRole('button', { name: 'Check again' })
    await waitFor(() => expect(button).toBeEnabled())
    await userEvent.click(button)
    expect(await screen.findByText('API OK')).toBeInTheDocument()
  })
})

describe('createApiClient', () => {
  it('raises ApiError with status on non-2xx', async () => {
    const api = createApiClient(async () => jsonResponse({}, 404))
    await expect(api.version()).rejects.toEqual(expect.objectContaining({ status: 404 }))
    await expect(api.version()).rejects.toBeInstanceOf(ApiError)
  })
})
