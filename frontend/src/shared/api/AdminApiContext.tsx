import { createContext, useContext, type ReactNode } from 'react'

import type { AdminApiClient } from './adminClient'

const AdminApiContext = createContext<AdminApiClient | null>(null)

export function AdminApiProvider({ client, children }: { client: AdminApiClient; children: ReactNode }) {
  return <AdminApiContext.Provider value={client}>{children}</AdminApiContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAdminApi(): AdminApiClient {
  const client = useContext(AdminApiContext)
  if (client === null) {
    throw new Error('useAdminApi must be used inside AdminApiProvider')
  }
  return client
}
