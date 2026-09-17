import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'

import { App } from '../../../app/App'
import { routes } from '../../../app/router'
import { createAdminApiClient } from '../../../shared/api/adminClient'
import { createApiClient } from '../../../shared/api/client'
import type { DeviceKeyStore } from '../../../shared/api/deviceKey'
import { DEVICE_KEY, FakeAdminServer } from './fakeAdminServer'

export function renderAdmin(
  path: string,
  { server = new FakeAdminServer(), paired = true }: { server?: FakeAdminServer; paired?: boolean } = {},
) {
  let key: string | null = paired ? DEVICE_KEY : null
  const keys: DeviceKeyStore = {
    get: () => key,
    set: (value) => {
      key = value
    },
    clear: () => {
      key = null
    },
  }
  const adminClient = createAdminApiClient(server.fetcher, keys)
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const view = render(
    <App instance="dummy" apiClient={createApiClient(server.fetcher, keys)} adminClient={adminClient}>
      <RouterProvider router={router} />
    </App>,
  )
  return { ...view, server, router, adminClient }
}
