import { useState } from 'react'
import { Link } from 'react-router'

import { AdminApiError, type EventProfile } from '../../../shared/api/adminClient'
import { BigButton } from '../../../shared/ui/BigButton'
import {
  useActivateProfile,
  useDeleteProfile,
  useDuplicateProfile,
  useProfiles,
  useRestoreProfile,
} from '../api/hooks'
import { PillButton } from '../components/ui/Controls'
import { MessageDialog } from '../components/ui/MessageDialog'
import styles from './ProfileListPage.module.css'

function extractErrorMessages(err: unknown): string[] {
  if (err instanceof AdminApiError) {
    return err.messages.length > 0 ? err.messages : [err.message]
  }
  if (err instanceof Error) {
    return [err.message]
  }
  return ['An unexpected error occurred.']
}

export function ProfileListPage() {
  const [showDeleted, setShowDeleted] = useState(false)
  const [deletingProfile, setDeletingProfile] = useState<EventProfile | null>(null)
  const [mutationErrors, setMutationErrors] = useState<string[] | null>(null)
  const [activationStatus, setActivationStatus] = useState<string | null>(null)

  const { data: profiles = [], error: profilesError } = useProfiles(showDeleted)
  const activateMutation = useActivateProfile()
  const [activationError, setActivationError] = useState<{ id: string; messages: string[] } | null>(
    null,
  )
  const duplicateMutation = useDuplicateProfile()
  const deleteMutation = useDeleteProfile()
  const restoreMutation = useRestoreProfile()

  const handleDuplicate = async (profile: EventProfile) => {
    setMutationErrors(null)
    setActivationStatus(null)
    try {
      await duplicateMutation.mutateAsync({ id: profile.id })
    } catch (err: unknown) {
      setMutationErrors(extractErrorMessages(err))
    }
  }

  const handleActivate = async (profile: EventProfile) => {
    setMutationErrors(null)
    setActivationStatus(null)
    setActivationError(null)
    try {
      await activateMutation.mutateAsync(profile.id)
      setActivationStatus(`${profile.settings.name} is now the active profile.`)
    } catch (err: unknown) {
      // Shown right under that profile (e.g. no frames available to participants).
      setActivationError({ id: profile.id, messages: extractErrorMessages(err) })
    }
  }

  const handleRestore = async (profile: EventProfile) => {
    setMutationErrors(null)
    setActivationStatus(null)
    try {
      await restoreMutation.mutateAsync(profile.id)
    } catch (err: unknown) {
      setMutationErrors(extractErrorMessages(err))
    }
  }

  const handleConfirmDelete = async () => {
    if (!deletingProfile) return
    setMutationErrors(null)
    setActivationStatus(null)
    try {
      await deleteMutation.mutateAsync({
        id: deletingProfile.id,
        revision: deletingProfile.revision,
      })
      setDeletingProfile(null)
    } catch (err: unknown) {
      setDeletingProfile(null)
      setMutationErrors(extractErrorMessages(err))
    }
  }

  const loadErrors = profilesError ? extractErrorMessages(profilesError) : null
  const refused = activationError ? profiles.find((p) => p.id === activationError.id) : undefined

  return (
    <div className={styles.container}>
      <div className={styles.topBar}>
        <h1 className={styles.heading}>Event Profiles</h1>
        <div className={styles.actionsBar}>
          <Link to="/admin/profiles/new" className={styles.newProfileLink}>
            New profile
          </Link>
          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={showDeleted}
              onChange={(e) => setShowDeleted(e.target.checked)}
              className={styles.checkbox}
            />
            Show deleted profiles
          </label>
        </div>
      </div>

      {activationStatus && (
        <div role="status" className={styles.status}>
          {activationStatus}
        </div>
      )}

      {loadErrors && loadErrors.length > 0 && (
        <div role="alert" className={styles.alert}>
          {loadErrors.map((msg, index) => (
            <p key={index}>{msg}</p>
          ))}
        </div>
      )}

      {profiles.length === 0 ? (
        <p className={styles.emptyState}>No event profiles yet.</p>
      ) : (
        <ul className={styles.profileList}>
          {profiles.map((profile) => {
            const isDeleted = profile.deleted_at !== null

            return (
              <li key={profile.id} data-testid="profile-row" className={styles.profileRow}>
                <div className={styles.profileInfo}>
                  <div className={styles.profileHeading}>
                    <span className={styles.profileName}>{profile.settings.name}</span>
                    {profile.is_active && <span className={styles.badgeActive}>Active</span>}
                    {isDeleted && <span className={styles.badgeDeleted}>Deleted</span>}
                  </div>
                  <div className={styles.profileTitle}>{profile.settings.title}</div>
                  <div className={styles.profileTitle}>
                    {profile.settings.available_frames.length === 1
                      ? '1 frame for participants'
                      : `${profile.settings.available_frames.length} frames for participants`}
                  </div>
                </div>

                <div className={styles.rowActions}>
                  {isDeleted ? (
                    <BigButton
                      type="button"
                      onClick={() => {
                        void handleRestore(profile)
                      }}
                    >
                      Restore {profile.settings.name}
                    </BigButton>
                  ) : (
                    <>
                      <Link to={`/admin/profiles/${profile.id}`} className={styles.actionLink}>
                        Edit {profile.settings.name}
                      </Link>
                      <BigButton
                        type="button"
                        onClick={() => {
                          void handleDuplicate(profile)
                        }}
                      >
                        Duplicate {profile.settings.name}
                      </BigButton>
                      <BigButton
                        type="button"
                        disabled={profile.is_active}
                        onClick={() => {
                          void handleActivate(profile)
                        }}
                      >
                        Activate {profile.settings.name}
                      </BigButton>
                      <div className={styles.deleteWrapper}>
                        <BigButton
                          type="button"
                          disabled={profile.is_active}
                          onClick={() => setDeletingProfile(profile)}
                          title={
                            profile.is_active
                              ? 'Activate another profile before deleting this one.'
                              : undefined
                          }
                        >
                          Delete {profile.settings.name}
                        </BigButton>
                        {profile.is_active && (
                          <span className={styles.deleteHint}>
                            Activate another profile before deleting this one.
                          </span>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {deletingProfile && (
        <MessageDialog
          kind="confirm"
          title={`Delete ${deletingProfile.settings.name}?`}
          onClose={() => setDeletingProfile(null)}
          actions={
            <PillButton
              tone="danger"
              disabled={deleteMutation.isPending}
              onClick={() => {
                void handleConfirmDelete()
              }}
            >
              Delete profile
            </PillButton>
          }
        >
          <p>The profile is hidden but can be restored later.</p>
        </MessageDialog>
      )}

      {activationError && (
        <MessageDialog
          kind="warning"
          title={`${refused?.settings.name ?? 'This profile'} can not be activated`}
          testId="activation-error"
          onClose={() => setActivationError(null)}
          actions={
            <Link to={`/admin/profiles/${activationError.id}`} className={styles.dialogLink}>
              Choose frames for {refused?.settings.name ?? 'this profile'}
            </Link>
          }
        >
          {activationError.messages.map((msg, index) => (
            <p key={index}>{msg}</p>
          ))}
        </MessageDialog>
      )}

      {mutationErrors && mutationErrors.length > 0 && (
        <MessageDialog kind="error" title="That did not work" onClose={() => setMutationErrors(null)}>
          {mutationErrors.map((msg, index) => (
            <p key={index}>{msg}</p>
          ))}
        </MessageDialog>
      )}    </div>
  )
}
