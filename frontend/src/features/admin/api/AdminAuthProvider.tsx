import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { AdminApiError } from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import { ADMIN_QUERY_ROOT } from './queryKeys'

export type AdminAuthStatus =
  | 'checking'
  | 'not-paired' // this browser has no kiosk device key: pair first (scripts\run-dummy.ps1 -PairOnly)
  | 'signed-out'
  | 'expired' // was signed in; the server no longer accepts the session
  | 'signed-in'
  | 'error' // server unreachable

export interface AdminAuth {
  status: AdminAuthStatus
  username: string | null
  /** Resolves on success; rejects with AdminApiError (401 wrong credentials, 429 throttled, ...). */
  login(username: string, password: string): Promise<void>
  logout(): Promise<void>
  recheck(): void
}

const AdminAuthContext = createContext<AdminAuth | null>(null)

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const api = useAdminApi()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<AdminAuthStatus>(() =>
    api.isPaired() ? 'checking' : 'not-paired',
  )
  const [username, setUsername] = useState<string | null>(null)
  const [generation, setGeneration] = useState(0)

  useEffect(() => {
    let cancelled = false
    if (!api.isPaired()) {
      return
    }
    api
      .session()
      .then((session) => {
        if (cancelled) return
        setUsername(session?.username ?? null)
        setStatus(session ? 'signed-in' : 'signed-out')
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setStatus(error instanceof AdminApiError && error.kind === 'not-paired' ? 'not-paired' : 'error')
      })
    return () => {
      cancelled = true
    }
  }, [api, generation])

  useEffect(
    () =>
      api.onSessionChange((event) => {
        if (event === 'signed-in') return
        // Never keep showing admin data after the session is gone.
        queryClient.removeQueries({ queryKey: ADMIN_QUERY_ROOT })
        setUsername(null)
        setStatus(event)
      }),
    [api, queryClient],
  )

  const login = useCallback(
    async (name: string, password: string) => {
      const session = await api.login(name, password)
      setUsername(session.username)
      setStatus('signed-in')
    },
    [api],
  )
  const logout = useCallback(() => api.logout(), [api])
  const recheck = useCallback(() => {
    setStatus(api.isPaired() ? 'checking' : 'not-paired')
    setGeneration((g) => g + 1)
  }, [api])

  const value = useMemo<AdminAuth>(
    () => ({ status, username, login, logout, recheck }),
    [status, username, login, logout, recheck],
  )
  return <AdminAuthContext.Provider value={value}>{children}</AdminAuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAdminAuth(): AdminAuth {
  const auth = useContext(AdminAuthContext)
  if (auth === null) {
    throw new Error('useAdminAuth must be used inside AdminAuthProvider')
  }
  return auth
}
