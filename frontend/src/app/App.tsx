import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { createAdminApiClient, type AdminApiClient } from '../shared/api/adminClient'
import { AdminApiProvider } from '../shared/api/AdminApiContext'
import { ApiClientProvider } from '../shared/api/ApiClientContext'
import type { ApiClient } from '../shared/api/client'
import type { InstanceName } from '../shared/config/instance'
import { DummyBadge } from '../shared/ui/DummyBadge'

const unpairedKeys = { get: () => null, set: () => undefined, clear: () => undefined }

export function App({
  instance,
  apiClient,
  adminClient,
  children,
}: {
  instance: InstanceName
  apiClient?: ApiClient
  adminClient?: AdminApiClient
  children: ReactNode
}) {
  const [queryClient] = useState(() => new QueryClient())
  const [admin] = useState<AdminApiClient>(
    () => adminClient ?? createAdminApiClient(undefined, unpairedKeys),
  )
  return (
    <QueryClientProvider client={queryClient}>
      <ApiClientProvider {...(apiClient ? { client: apiClient } : {})}>
        <AdminApiProvider client={admin}>
          <DummyBadge instance={instance} />
          {children}
        </AdminApiProvider>
      </ApiClientProvider>
    </QueryClientProvider>
  )
}