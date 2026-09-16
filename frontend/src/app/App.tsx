import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { ApiClientProvider } from '../shared/api/ApiClientContext'
import type { ApiClient } from '../shared/api/client'
import type { InstanceName } from '../shared/config/instance'
import { DummyBadge } from '../shared/ui/DummyBadge'

export function App({
  instance,
  apiClient,
  children,
}: {
  instance: InstanceName
  apiClient?: ApiClient
  children: ReactNode
}) {
  const [queryClient] = useState(() => new QueryClient())
  return (
    <QueryClientProvider client={queryClient}>
      <ApiClientProvider {...(apiClient ? { client: apiClient } : {})}>
        <DummyBadge instance={instance} />
        {children}
      </ApiClientProvider>
    </QueryClientProvider>
  )
}
