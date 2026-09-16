import { useQuery } from '@tanstack/react-query'

import { useApiClient } from '../../shared/api/ApiClientContext'

export function useHealth() {
  const api = useApiClient()
  return useQuery({ queryKey: ['system', 'health'], queryFn: api.health, retry: false })
}

export function useKioskStatus() {
  const api = useApiClient()
  return useQuery({ queryKey: ['kiosk', 'status'], queryFn: api.kioskStatus, retry: false })
}
