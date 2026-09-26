import { useQuery } from '@tanstack/react-query'

import { useBoothServices } from './boothServices'

/**
 * The event as the booth screens see it (start screen, theme and frames).
 *
 * Guests get the active event; the Admin "Test booth" page gets the saved profile it is trying.
 */
export function useBoothMenu() {
  const booth = useBoothServices()
  return useQuery({ queryKey: [...booth.key], queryFn: () => booth.menu(), retry: false })
}