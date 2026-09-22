import { useQuery } from '@tanstack/react-query'

import { useApiClient } from '../../shared/api/ApiClientContext'

/** The active event as the participant screens see it (start screen, theme and frames). */
export function useBoothMenu() {
  const api = useApiClient()
  return useQuery({ queryKey: ['booth', 'frames'], queryFn: () => api.frameMenu(), retry: false })
}
