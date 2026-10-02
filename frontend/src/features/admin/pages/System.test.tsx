import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

/** Phase 12: the organizer's System page. */
describe('System', () => {
  it('shows versions, health, disk, addresses and the last cleanup', async () => {
    const server = new FakeAdminServer()
    server.signedIn = true
    renderAdmin('/admin/system', { server })
    const health = await screen.findByRole('region', { name: 'Health' })
    expect(within(health).getByText('OK')).toBeInTheDocument()
    expect(within(health).getByText('120.0 GB of 476.0 GB')).toBeInTheDocument()
    expect(within(health).getByText('Garden Party')).toBeInTheDocument()
    const addresses = screen.getByRole('region', { name: 'Addresses' })
    expect(within(addresses).getByText('http://192.168.1.20:8113')).toBeInTheDocument()
    expect(within(addresses).getByText('http://127.0.0.1:8111/booth')).toBeInTheDocument()
    const version = screen.getByRole('region', { name: 'Version' })
    expect(within(version).getByText('7328935d7c92')).toBeInTheDocument()
    expect(within(version).getByText('0011_retention')).toBeInTheDocument()
  })

  it('warns when the disk is nearly full or the database does not answer', async () => {
    const server = new FakeAdminServer()
    server.signedIn = true
    server.systemDetails = {
      ...server.systemDetails,
      database: 'error',
      disk_free_bytes: 1024 ** 3,
    }
    renderAdmin('/admin/system', { server })
    const health = await screen.findByRole('region', { name: 'Health' })
    expect(within(health).getByText('Not answering')).toBeInTheDocument()
    expect(within(health).getByText(/low, clean up or free space/)).toBeInTheDocument()
  })
})