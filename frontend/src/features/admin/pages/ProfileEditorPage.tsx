import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import {
  AdminApiError,
  INACTIVITY_LIMITS,
  newProfileSettings,
  TEXT_LIMITS,
  type EventProfile,
  type ProfileSettings,
  type TemplateSummary,
} from '../../../shared/api/adminClient'
import { BigButton } from '../../../shared/ui/BigButton'
import { useCreateProfile, useProfile, useTemplates, useUpdateProfile } from '../api/hooks'
import { AssetPicker } from '../components/AssetPicker'
import { PreparationPreview } from '../components/PreparationPreview'
import styles from './ProfileEditorPage.module.css'

interface ProfileEditorFormProps {
  initialSettings: ProfileSettings
  initialRevision: number
  templates: TemplateSummary[]
  profileId?: string
  isNew: boolean
  isDeleted: boolean
  onReloadLatest: () => Promise<EventProfile | undefined>
}

function ProfileEditorForm({
  initialSettings,
  initialRevision,
  templates,
  profileId,
  isNew,
  isDeleted,
  onReloadLatest,
}: ProfileEditorFormProps) {
  const navigate = useNavigate()
  const createMutation = useCreateProfile()
  const updateMutation = useUpdateProfile()

  const [settings, setSettings] = useState<ProfileSettings>(() => initialSettings)
  const [currentRevision, setCurrentRevision] = useState<number>(() => initialRevision)
  const [isSaving, setIsSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState<string | null>(null)
  const [clientErrors, setClientErrors] = useState<string[] | null>(null)
  const [serverErrors, setServerErrors] = useState<string[] | null>(null)
  const [conflictError, setConflictError] = useState<{
    message: string
    serverMessage?: string
  } | null>(null)

  const validate = (): string[] => {
    const errors: string[] = []
    if (!settings.name.trim()) {
      errors.push('Profile name is required.')
    }
    if (!settings.title.trim()) {
      errors.push('Title is required.')
    }
    if (
      isNaN(settings.inactivity_timeout_s) ||
      settings.inactivity_timeout_s < INACTIVITY_LIMITS.min ||
      settings.inactivity_timeout_s > INACTIVITY_LIMITS.max
    ) {
      errors.push(
        `Inactivity timeout must be between ${INACTIVITY_LIMITS.min} and ${INACTIVITY_LIMITS.max} seconds.`,
      )
    }
    if (settings.enabled_layouts.length === 0) {
      errors.push('Choose at least one layout.')
    }
    return errors
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setSaveStatus(null)
    setServerErrors(null)
    setConflictError(null)

    const errors = validate()
    if (errors.length > 0) {
      setClientErrors(errors)
      return
    }
    setClientErrors(null)

    setIsSaving(true)
    try {
      if (isNew) {
        const created = await createMutation.mutateAsync(settings)
        void navigate(`/admin/profiles/${created.id}`)
      } else if (profileId) {
        const updated = await updateMutation.mutateAsync({
          id: profileId,
          settings,
          revision: currentRevision,
        })
        setCurrentRevision(updated.revision)
        setSaveStatus('Saved')
      }
    } catch (err: unknown) {
      if (err instanceof AdminApiError && err.kind === 'conflict') {
        setConflictError({
          message: 'This profile was changed somewhere else. Reload to get the latest version.',
          serverMessage: err.messages[0] ?? err.message,
        })
      } else if (err instanceof AdminApiError) {
        setServerErrors(err.messages.length > 0 ? err.messages : [err.message])
      } else if (err instanceof Error) {
        setServerErrors([err.message])
      } else {
        setServerErrors(['Save failed.'])
      }
    } finally {
      setIsSaving(false)
    }
  }

  const handleReloadLatest = async () => {
    const fresh = await onReloadLatest()
    if (fresh) {
      setSettings(fresh.settings)
      setCurrentRevision(fresh.revision)
      setConflictError(null)
      setServerErrors(null)
      setClientErrors(null)
      setSaveStatus(null)
    }
  }

  return (
    <div className={styles.editorLayout}>
      <form onSubmit={handleSubmit} className={styles.formColumn}>
        {isDeleted && (
          <div role="alert" className={styles.alert}>
            This profile is deleted. Restore it from the list to edit.
          </div>
        )}

        {saveStatus && (
          <div role="status" className={styles.status}>
            {saveStatus}
          </div>
        )}

        {clientErrors && clientErrors.length > 0 && (
          <div role="alert" className={styles.alert}>
            <ul>
              {clientErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        {serverErrors && serverErrors.length > 0 && (
          <div role="alert" className={styles.alert}>
            <ul>
              {serverErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        {conflictError && (
          <div role="alert" className={styles.alert}>
            <p>{conflictError.message}</p>
            {conflictError.serverMessage && <p>{conflictError.serverMessage}</p>}
            <BigButton
              type="button"
              onClick={() => {
                void handleReloadLatest()
              }}
            >
              Reload latest
            </BigButton>
          </div>
        )}

        {/* Profile Section */}
        <section className={styles.formSection}>
          <h2 className={styles.sectionHeading}>Profile</h2>
          <div className={styles.field}>
            <label htmlFor="field-profile-name" className={styles.label}>
              Profile name
            </label>
            <input
              id="field-profile-name"
              type="text"
              maxLength={TEXT_LIMITS.name}
              value={settings.name}
              onChange={(e) => setSettings({ ...settings, name: e.target.value })}
              className={styles.input}
              disabled={isDeleted}
            />
          </div>
        </section>

        {/* Preparation Screen Section */}
        <section className={styles.formSection}>
          <h2 className={styles.sectionHeading}>Preparation screen</h2>
          <div className={styles.field}>
            <label htmlFor="field-title" className={styles.label}>
              Title
            </label>
            <input
              id="field-title"
              type="text"
              maxLength={TEXT_LIMITS.title}
              value={settings.title}
              onChange={(e) => setSettings({ ...settings, title: e.target.value })}
              className={styles.input}
              disabled={isDeleted}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="field-subtitle" className={styles.label}>
              Subtitle
            </label>
            <textarea
              id="field-subtitle"
              maxLength={TEXT_LIMITS.subtitle}
              value={settings.subtitle}
              onChange={(e) => setSettings({ ...settings, subtitle: e.target.value })}
              className={styles.textarea}
              disabled={isDeleted}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="field-start-button-text" className={styles.label}>
              Start button text
            </label>
            <input
              id="field-start-button-text"
              type="text"
              maxLength={TEXT_LIMITS.startButtonText}
              value={settings.start_button_text}
              onChange={(e) => setSettings({ ...settings, start_button_text: e.target.value })}
              className={styles.input}
              disabled={isDeleted}
            />
          </div>
        </section>

        {/* Colors Section */}
        <section className={styles.formSection}>
          <h2 className={styles.sectionHeading}>Colors</h2>
          <div className={styles.colorGrid}>
            <div className={styles.colorField}>
              <label htmlFor="color-background" className={styles.label}>
                Background color
              </label>
              <div className={styles.colorInputWrapper}>
                <input
                  id="color-background"
                  type="color"
                  value={settings.background_color}
                  onChange={(e) =>
                    setSettings({ ...settings, background_color: e.target.value.toUpperCase() })
                  }
                  className={styles.colorInput}
                  disabled={isDeleted}
                />
                <span className={styles.colorHex}>{settings.background_color}</span>
              </div>
            </div>

            <div className={styles.colorField}>
              <label htmlFor="color-primary" className={styles.label}>
                Primary color
              </label>
              <div className={styles.colorInputWrapper}>
                <input
                  id="color-primary"
                  type="color"
                  value={settings.primary_color}
                  onChange={(e) =>
                    setSettings({ ...settings, primary_color: e.target.value.toUpperCase() })
                  }
                  className={styles.colorInput}
                  disabled={isDeleted}
                />
                <span className={styles.colorHex}>{settings.primary_color}</span>
              </div>
            </div>

            <div className={styles.colorField}>
              <label htmlFor="color-secondary" className={styles.label}>
                Secondary color
              </label>
              <div className={styles.colorInputWrapper}>
                <input
                  id="color-secondary"
                  type="color"
                  value={settings.secondary_color}
                  onChange={(e) =>
                    setSettings({ ...settings, secondary_color: e.target.value.toUpperCase() })
                  }
                  className={styles.colorInput}
                  disabled={isDeleted}
                />
                <span className={styles.colorHex}>{settings.secondary_color}</span>
              </div>
            </div>

            <div className={styles.colorField}>
              <label htmlFor="color-button" className={styles.label}>
                Button color
              </label>
              <div className={styles.colorInputWrapper}>
                <input
                  id="color-button"
                  type="color"
                  value={settings.button_color}
                  onChange={(e) =>
                    setSettings({ ...settings, button_color: e.target.value.toUpperCase() })
                  }
                  className={styles.colorInput}
                  disabled={isDeleted}
                />
                <span className={styles.colorHex}>{settings.button_color}</span>
              </div>
            </div>

            <div className={styles.colorField}>
              <label htmlFor="color-text" className={styles.label}>
                Text color
              </label>
              <div className={styles.colorInputWrapper}>
                <input
                  id="color-text"
                  type="color"
                  value={settings.text_color}
                  onChange={(e) =>
                    setSettings({ ...settings, text_color: e.target.value.toUpperCase() })
                  }
                  className={styles.colorInput}
                  disabled={isDeleted}
                />
                <span className={styles.colorHex}>{settings.text_color}</span>
              </div>
            </div>
          </div>
        </section>

        {/* Images Section */}
        <section className={styles.formSection}>
          <h2 className={styles.sectionHeading}>Images</h2>
          <AssetPicker
            kind="logo"
            assetId={settings.logo_asset_id}
            onChange={(id) => setSettings({ ...settings, logo_asset_id: id })}
            disabled={isDeleted}
          />
          <AssetPicker
            kind="background"
            assetId={settings.background_asset_id}
            onChange={(id) => setSettings({ ...settings, background_asset_id: id })}
            disabled={isDeleted}
          />
        </section>

        {/* Photo Layouts Section */}
        <section className={styles.formSection}>
          <h2 className={styles.sectionHeading}>Photo layouts</h2>
          {templates.map((tpl) => (
            <label key={tpl.key} className={styles.checkboxLabel}>
              <input
                type="checkbox"
                value={tpl.key}
                checked={settings.enabled_layouts.includes(tpl.key)}
                onChange={(e) => {
                  const checked = e.target.checked
                  const next = checked
                    ? [...settings.enabled_layouts, tpl.key]
                    : settings.enabled_layouts.filter((k) => k !== tpl.key)
                  setSettings({ ...settings, enabled_layouts: next })
                }}
                disabled={isDeleted}
                className={styles.checkbox}
              />
              {tpl.name}
            </label>
          ))}
          {settings.enabled_layouts.length === 0 && (
            <div role="alert" className={styles.alert}>
              Choose at least one layout.
            </div>
          )}
        </section>

        {/* Booth Behaviour Section */}
        <section className={styles.formSection}>
          <h2 className={styles.sectionHeading}>Booth behaviour</h2>
          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={settings.mirror}
              onChange={(e) => setSettings({ ...settings, mirror: e.target.checked })}
              disabled={isDeleted}
              className={styles.checkbox}
            />
            Mirror the camera preview
          </label>

          <div className={styles.field}>
            <label htmlFor="field-inactivity-timeout" className={styles.label}>
              Inactivity timeout (seconds)
            </label>
            <input
              id="field-inactivity-timeout"
              type="number"
              min={INACTIVITY_LIMITS.min}
              max={INACTIVITY_LIMITS.max}
              value={settings.inactivity_timeout_s}
              onChange={(e) => {
                const num = parseInt(e.target.value, 10)
                setSettings({
                  ...settings,
                  inactivity_timeout_s: isNaN(num) ? 0 : num,
                })
              }}
              className={styles.input}
              disabled={isDeleted}
            />
          </div>

          <p className={styles.readOnlyText}>Countdown: 5 seconds before each photo</p>

          <fieldset className={styles.fieldset} disabled={isDeleted}>
            <legend className={styles.legend}>Retakes</legend>
            <label className={styles.radioLabel}>
              <input
                type="radio"
                name="retake_mode"
                value="none"
                checked={settings.retake_mode === 'none'}
                onChange={() => setSettings({ ...settings, retake_mode: 'none' })}
                className={styles.radio}
              />
              No retakes
            </label>
            <label className={styles.radioLabel}>
              <input
                type="radio"
                name="retake_mode"
                value="per_photo"
                checked={settings.retake_mode === 'per_photo'}
                onChange={() => setSettings({ ...settings, retake_mode: 'per_photo' })}
                className={styles.radio}
              />
              Retake any single photo
            </label>
            <label className={styles.radioLabel}>
              <input
                type="radio"
                name="retake_mode"
                value="all"
                checked={settings.retake_mode === 'all'}
                onChange={() => setSettings({ ...settings, retake_mode: 'all' })}
                className={styles.radio}
              />
              Retake all photos
            </label>
          </fieldset>

          <p className={styles.readOnlyText}>Delivery: QR code link on the local network</p>
        </section>

        <BigButton
          type="submit"
          disabled={isDeleted || isSaving}
          className={styles.saveButton}
        >
          Save profile
        </BigButton>
      </form>

      <div className={styles.previewColumn}>
        <PreparationPreview settings={settings} templates={templates} />
      </div>
    </div>
  )
}

export function ProfileEditorPage() {
  const { profileId } = useParams<{ profileId?: string }>()
  const isNew = !profileId

  const { data: templates, isLoading: isTemplatesLoading } = useTemplates()
  const {
    data: profile,
    isLoading: isProfileLoading,
    error: profileError,
    refetch: refetchProfile,
  } = useProfile(profileId)

  if (isTemplatesLoading || (!isNew && isProfileLoading)) {
    return (
      <div className={styles.container}>
        <div className={styles.headerRow}>
          <h1 className={styles.heading}>{isNew ? 'New Event Profile' : 'Edit Event Profile'}</h1>
          <Link to="/admin" className={styles.backLink}>
            Back to profiles
          </Link>
        </div>
        <p>Loading…</p>
      </div>
    )
  }

  if (!templates) {
    return (
      <div className={styles.container}>
        <div className={styles.headerRow}>
          <h1 className={styles.heading}>{isNew ? 'New Event Profile' : 'Edit Event Profile'}</h1>
          <Link to="/admin" className={styles.backLink}>
            Back to profiles
          </Link>
        </div>
        <div role="alert" className={styles.alert}>
          Unable to load templates.
        </div>
      </div>
    )
  }

  if (!isNew && (profileError !== null || profile === undefined)) {
    return (
      <div className={styles.container}>
        <div className={styles.headerRow}>
          <h1 className={styles.heading}>Edit Event Profile</h1>
          <Link to="/admin" className={styles.backLink}>
            Back to profiles
          </Link>
        </div>
        <div role="alert" className={styles.alert}>
          Profile not found or could not be loaded.
        </div>
      </div>
    )
  }

  // Narrowed above: an existing profile is loaded whenever this is not a new one.
  const loaded = isNew ? undefined : profile
  const initialSettings = loaded?.settings ?? newProfileSettings(templates.map((t) => t.key))
  const initialRevision = loaded?.revision ?? 1
  const isDeleted = loaded !== undefined && loaded.deleted_at !== null

  const handleReloadLatest = async (): Promise<EventProfile | undefined> => {
    const res = await refetchProfile()
    return res.data
  }

  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        <h1 className={styles.heading}>{isNew ? 'New Event Profile' : 'Edit Event Profile'}</h1>
        <Link to="/admin" className={styles.backLink}>
          Back to profiles
        </Link>
      </div>

      <ProfileEditorForm
        key={loaded?.id ?? 'new'}
        initialSettings={initialSettings}
        initialRevision={initialRevision}
        templates={templates}
        {...(loaded ? { profileId: loaded.id } : {})}
        isNew={isNew}
        isDeleted={isDeleted}
        onReloadLatest={handleReloadLatest}
      />
    </div>
  )
}
