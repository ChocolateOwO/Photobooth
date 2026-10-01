import { createContext, useContext, useMemo } from 'react'
import { useNavigate } from 'react-router'

import { useAdminApi } from '../../shared/api/AdminApiContext'
import { useApiClient } from '../../shared/api/ApiClientContext'
import type { BoothSessionState, FrameMenu } from '../../shared/api/client'

/**
 * Where the booth screens get their event and their visit.
 *
 * The real booth asks the participant API about the active event. The Admin "Test booth" page
 * asks the admin API about a saved profile instead, and its visits are marked as tests. Every
 * screen below this is the same in both cases: there is no second copy of the booth.
 */

/** The screens of a visit, in the order they come. */
export type BoothStep = 'start' | 'frames' | 'capture' | 'done'

export interface BoothServices {
  /** An organizer trying the booth from Admin, rather than a guest at the event. */
  readonly isTest: boolean
  /** Cache key, so a test of another profile never shows the active event's frames. */
  readonly key: readonly string[]
  menu(): Promise<FrameMenu>
  startVisit(idempotencyKey: string): Promise<BoothSessionState>
  /** Move to another booth screen. The real booth walks its addresses; a test stays in Admin. */
  go(step: BoothStep, options?: { replace?: boolean }): void
}

const BOOTH_PATHS: Record<BoothStep, string> = {
  start: '/booth',
  frames: '/booth/frames',
  capture: '/booth/capture',
  done: '/booth/done',
}

/** Wrap booth screens in this to run them against something other than the live event. */
export const BoothServicesContext = createContext<BoothServices | null>(null)

/** The booth as guests use it: the active event, through the participant API. */
export function useParticipantBooth(): BoothServices {
  const api = useApiClient()
  const navigate = useNavigate()
  return useMemo(
    () => ({
      isTest: false,
      key: ['booth', 'menu'],
      menu: () => api.frameMenu(),
      startVisit: (idempotencyKey: string) => api.startSession(idempotencyKey),
      go: (step, options) =>
        void navigate(BOOTH_PATHS[step], options?.replace ? { replace: true } : {}),
    }),
    [api, navigate],
  )
}

/** The same booth, run by an organizer against a saved profile (never activating it). */
export function useProfileTestBooth(
  profileId: string,
  go: (step: BoothStep) => void,
): BoothServices {
  const admin = useAdminApi()
  return useMemo(
    () => ({
      isTest: true,
      key: ['booth', 'test', profileId],
      menu: () => admin.boothTestMenu(profileId),
      startVisit: (idempotencyKey: string) => admin.startBoothTest(profileId, idempotencyKey),
      // The test stays on the Admin page: only which booth screen is shown changes.
      go: (step) => go(step),
    }),
    [admin, go, profileId],
  )
}

/** The booth screens read this; without a provider they serve guests, as the real booth does. */
export function useBoothServices(): BoothServices {
  const participant = useParticipantBooth()
  return useContext(BoothServicesContext) ?? participant
}
