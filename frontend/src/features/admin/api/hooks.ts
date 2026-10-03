import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import type {
  AssetKind,
  EventProfile,
  HistoryQuery,
  NewProfileSettings,
  PeriodQuery,
  Housekeeping,
  RetentionPolicyBody,
  ProfileSettings,
} from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import { ADMIN_QUERY_ROOT } from './queryKeys'

/**
 * Data hooks for the admin UI. Every contract comes from the generated OpenAPI types through
 * AdminApiClient; UI code must not call fetch directly.
 */
export const adminKeys = {
  profiles: (includeDeleted: boolean) => [...ADMIN_QUERY_ROOT, 'profiles', { includeDeleted }] as const,
  profile: (id: string) => [...ADMIN_QUERY_ROOT, 'profile', id] as const,
  asset: (id: string) => [...ADMIN_QUERY_ROOT, 'asset', id] as const,
  templates: () => ['templates'] as const,
  templateSpec: (key: string) => ['templates', key] as const,
  frames: (templateKey?: string) => [...ADMIN_QUERY_ROOT, 'frames', templateKey ?? 'all'] as const,
  themes: () => [...ADMIN_QUERY_ROOT, 'themes'] as const,
  activity: (actors: readonly string[]) => [...ADMIN_QUERY_ROOT, 'activity', actors] as const,
  history: (q: HistoryQuery) => [...ADMIN_QUERY_ROOT, 'history', q] as const,
  visit: (id: string) => [...ADMIN_QUERY_ROOT, 'visit', id] as const,
  statistics: (q: PeriodQuery) => [...ADMIN_QUERY_ROOT, 'statistics', q] as const,
  retention: () => [...ADMIN_QUERY_ROOT, 'retention'] as const,
}

const noRetry = { retry: false } as const

export function useTemplates() {
  const api = useAdminApi()
  return useQuery({ queryKey: adminKeys.templates(), queryFn: () => api.templates(), ...noRetry })
}

export function useProfiles(includeDeleted = false) {
  const api = useAdminApi()
  return useQuery({
    queryKey: adminKeys.profiles(includeDeleted),
    queryFn: () => api.listProfiles(includeDeleted),
    ...noRetry,
  })
}

export function useProfile(id: string | undefined) {
  const api = useAdminApi()
  return useQuery({
    queryKey: adminKeys.profile(id ?? ''),
    queryFn: () => api.getProfile(id ?? ''),
    enabled: id !== undefined,
    ...noRetry,
  })
}

export function useAsset(id: string | null | undefined) {
  const api = useAdminApi()
  return useQuery({
    queryKey: adminKeys.asset(id ?? ''),
    queryFn: () => api.getAsset(id ?? ''),
    enabled: Boolean(id),
    ...noRetry,
  })
}

/** Refresh every profile view after a change and seed the changed profile. */
function useProfileMutation<TArgs>(run: (args: TArgs) => Promise<EventProfile>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: async (profile) => {
      queryClient.setQueryData(adminKeys.profile(profile.id), profile)
      await queryClient.invalidateQueries({ queryKey: [...ADMIN_QUERY_ROOT, 'profiles'] })
    },
  })
}

export function useCreateProfile() {
  const api = useAdminApi()
  return useProfileMutation((settings: NewProfileSettings) => api.createProfile(settings))
}

export function useUpdateProfile() {
  const api = useAdminApi()
  return useProfileMutation(
    ({ id, settings, revision }: { id: string; settings: ProfileSettings; revision: number }) =>
      api.updateProfile(id, settings, revision),
  )
}

export function useDuplicateProfile() {
  const api = useAdminApi()
  return useProfileMutation(({ id, name }: { id: string; name?: string }) =>
    api.duplicateProfile(id, name),
  )
}

export function useActivateProfile() {
  const api = useAdminApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.activateProfile(id),
    // Activation changes other profiles too: drop every cached profile.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ADMIN_QUERY_ROOT }),
  })
}

export function useDeleteProfile() {
  const api = useAdminApi()
  return useProfileMutation(({ id, revision }: { id: string; revision: number }) =>
    api.deleteProfile(id, revision),
  )
}

export function useRestoreProfile() {
  const api = useAdminApi()
  return useProfileMutation((id: string) => api.restoreProfile(id))
}

export function useTemplateSpec(key: string | undefined) {
  const api = useAdminApi()
  return useQuery({
    queryKey: adminKeys.templateSpec(key ?? ''),
    queryFn: () => api.templateSpec(key ?? ''),
    enabled: key !== undefined,
    ...noRetry,
  })
}

export function useFrames(templateKey?: string, options: { enabled?: boolean } = {}) {
  const api = useAdminApi()
  return useQuery({
    queryKey: adminKeys.frames(templateKey),
    queryFn: () => api.listFrames(templateKey),
    enabled: options.enabled ?? true,
    // A failed list stays failed (with its Try again) instead of refetching whenever another
    // component mounts; that loop could keep a page switching between loading and error.
    retryOnMount: false,
    ...noRetry,
  })
}

/** Refresh every frame list after a change (frames are shown per layout and all together). */
function useFrameMutation<TArgs, TResult>(run: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [...ADMIN_QUERY_ROOT, 'frames'] }),
  })
}

export function useUploadFrame() {
  const api = useAdminApi()
  return useFrameMutation(
    ({ templateKey, name, file }: { templateKey: string; name: string; file: File }) =>
      api.uploadFrame(templateKey, name, file),
  )
}

export function useReplaceFrameFile() {
  const api = useAdminApi()
  return useFrameMutation(({ id, file }: { id: string; file: File }) =>
    api.replaceFrameFile(id, file),
  )
}

export function useRenameFrame() {
  const api = useAdminApi()
  return useFrameMutation(({ id, name }: { id: string; name: string }) => api.renameFrame(id, name))
}

export function useDeleteFrame() {
  const api = useAdminApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteFrame(id),
    // A deleted frame can change profile views too.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ADMIN_QUERY_ROOT }),
  })
}

/** Token list, contrast rules and presets (fixed for a running booth). */
export function useThemeCatalog() {
  const api = useAdminApi()
  return useQuery({
    queryKey: adminKeys.themes(),
    queryFn: () => api.themeCatalog(),
    staleTime: Infinity,
    ...noRetry,
  })
}

/** Extract a theme from an uploaded background (a proposal; the profile is saved separately). */
export function useExtractTheme() {
  const api = useAdminApi()
  return useMutation({
    mutationFn: (backgroundAssetId: string) => api.extractTheme(backgroundAssetId),
  })
}

export function useUploadAsset() {
  const api = useAdminApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, file }: { kind: AssetKind; file: File }) => api.uploadAsset(kind, file),
    onSuccess: (asset) => queryClient.setQueryData(adminKeys.asset(asset.id), asset),
  })
}

/** The activity log, a page at a time (newest first); "Show older" fetches the next page. */
export function useActivity(actors: readonly string[]) {
  const api = useAdminApi()
  return useInfiniteQuery({
    queryKey: adminKeys.activity(actors),
    queryFn: ({ pageParam }) => api.activity(actors, pageParam),
    initialPageParam: undefined as { at: string; id: string } | undefined,
    getNextPageParam: (last) => {
      const tail = last.records.at(-1)
      return last.more && tail ? { at: tail.at, id: tail.id } : undefined
    },
    ...noRetry,
  })
}

export function useHistory(q: HistoryQuery) {
  const api = useAdminApi()
  return useQuery({
    queryKey: adminKeys.history(q),
    queryFn: () => api.history(q),
    placeholderData: keepPreviousData,
    ...noRetry,
  })
}

export function useVisit(id: string) {
  const api = useAdminApi()
  return useQuery({ queryKey: adminKeys.visit(id), queryFn: () => api.visit(id), ...noRetry })
}

export function useStatistics(q: PeriodQuery) {
  const api = useAdminApi()
  return useQuery({
    queryKey: adminKeys.statistics(q),
    queryFn: () => api.statistics(q),
    placeholderData: keepPreviousData,
    ...noRetry,
  })
}

const policiesKey = () => [...adminKeys.retention(), 'policies'] as const
const housekeepingKey = () => [...adminKeys.retention(), 'housekeeping'] as const

/** The named retention policies (the default first), with how many profiles use each. */
export function useRetentionPolicies() {
  const api = useAdminApi()
  return useQuery({ queryKey: policiesKey(), queryFn: () => api.retentionPolicies(), ...noRetry })
}

export function useRetentionRuns() {
  const api = useAdminApi()
  return useQuery({
    queryKey: [...adminKeys.retention(), 'runs'],
    queryFn: () => api.retentionRuns(),
    ...noRetry,
  })
}

function policyBody(policy: RetentionPolicyBody): RetentionPolicyBody {
  return {
    name: policy.name,
    originals_days: policy.originals_days,
    outputs_days: policy.outputs_days,
    link_days: policy.link_days,
    metadata_mode: policy.metadata_mode,
    metadata_days: policy.metadata_days,
    revision: policy.revision,
  }
}

/** Adds a policy (`id` absent) or changes one; either way the list is read again. */
export function useSaveRetentionPolicy() {
  const api = useAdminApi()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, policy }: { id: string | null; policy: RetentionPolicyBody }) =>
      id === null
        ? api.createRetentionPolicy(policyBody(policy))
        : api.saveRetentionPolicy(id, policyBody(policy)),
    onSuccess: () => void client.invalidateQueries({ queryKey: policiesKey() }),
  })
}

export function useDeleteRetentionPolicy() {
  const api = useAdminApi()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteRetentionPolicy(id),
    onSuccess: () => void client.invalidateQueries({ queryKey: policiesKey() }),
  })
}

export function useMakeDefaultRetentionPolicy() {
  const api = useAdminApi()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.makeDefaultRetentionPolicy(id),
    onSuccess: () => void client.invalidateQueries({ queryKey: policiesKey() }),
  })
}

export function useHousekeeping() {
  const api = useAdminApi()
  return useQuery({ queryKey: housekeepingKey(), queryFn: () => api.housekeeping(), ...noRetry })
}

export function useSaveHousekeeping() {
  const api = useAdminApi()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (settings: Housekeeping) =>
      api.saveHousekeeping({
        temp_hours: settings.temp_hours,
        activity_log_days: settings.activity_log_days,
        backup_days: settings.backup_days,
        app_log_days: settings.app_log_days,
        revision: settings.revision,
      }),
    onSuccess: (saved) => client.setQueryData(housekeepingKey(), saved),
  })
}

export function useRunRetention() {
  const api = useAdminApi()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      dryRun,
      housekeepingRevision,
    }: {
      dryRun: boolean
      housekeepingRevision?: number
    }) => api.runRetention(dryRun, housekeepingRevision),
    onSuccess: () => void client.invalidateQueries({ queryKey: [...adminKeys.retention(), 'runs'] }),
  })
}

export function useRemoveEvent() {
  const api = useAdminApi()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, dryRun }: { id: string; dryRun: boolean }) => api.removeEvent(id, dryRun),
    onSuccess: (_result, { dryRun }) => {
      if (!dryRun) void client.invalidateQueries({ queryKey: [...ADMIN_QUERY_ROOT, 'profiles'] })
    },
  })
}

export function useSystemDetails() {
  const api = useAdminApi()
  return useQuery({
    queryKey: [...ADMIN_QUERY_ROOT, 'system'],
    queryFn: () => api.systemDetails(),
    ...noRetry,
  })
}
