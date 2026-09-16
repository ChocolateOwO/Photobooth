import { createContext, useContext, useState, type ReactNode } from 'react'

import { createApiClient, type ApiClient } from './client'

const ApiClientContext = createContext<ApiClient | null>(null)

export function ApiClientProvider({ client, children }: { client?: ApiClient; children: ReactNode }) {
  const [value] = useState<ApiClient>(() => client ?? createApiClient())
  return <ApiClientContext.Provider value={value}>{children}</ApiClientContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useApiClient(): ApiClient {
  const client = useContext(ApiClientContext)
  if (client === null) {
    throw new Error('useApiClient must be used inside ApiClientProvider')
  }
  return client
}
