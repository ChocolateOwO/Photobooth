import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { AssetKind, EventProfile, ProfileSettings } from '../../../shared/api/adminClient'
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
  return useProfileMutation((settings: ProfileSettings) => api.createProfile(settings))
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

export function useFrames(templateKey?: string) {
  const api = useAdminApi()
  return useQuery({
    queryKey: adminKeys.frames(templateKey),
    queryFn: () => api.listFrames(templateKey),
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

export function useUploadAsset() {
  const api = useAdminApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, file }: { kind: AssetKind; file: File }) => api.uploadAsset(kind, file),
    onSuccess: (asset) => queryClient.setQueryData(adminKeys.asset(asset.id), asset),
  })
}
