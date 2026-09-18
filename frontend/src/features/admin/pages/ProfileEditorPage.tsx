import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import {
  AdminApiError,
  INACTIVITY_LIMITS,
  newProfileSettings,
  presetTheme,
  TEXT_LIMITS,
  type EventProfile,
  type EventTheme,
  type ProfileSettings,
  type TemplateSummary,
  type ThemeCatalog,
} from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import { BigButton } from '../../../shared/ui/BigButton'
import {
  useCreateProfile,
  useExtractTheme,
  useFrames,
  useProfile,
  useTemplates,
  useThemeCatalog,
  useUpdateProfile,
} from '../api/hooks'
import { AssetPicker } from '../components/AssetPicker'
import { EventPreview } from '../components/EventPreview'
import { RetryingImage } from '../components/RetryingImage'
import { ThemeEditor } from '../components/ThemeEditor'
import { builtinFrameFor, preferredFamily } from '../frameDefaults'
import styles from './ProfileEditorPage.module.css'

/** Frame selections without one layout (no mutation of the current state). */
function withoutLayout(
  selections: Record<string, string> | undefined,
  templateKey: string,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(selections ?? {}).filter(([key]) => key !== templateKey),
  )
}

interface ProfileEditorFormProps {
  catalog: ThemeCatalog
  initialSettings: ProfileSettings
  initialRevision: number
  templates: TemplateSummary[]
  profileId?: string
  isNew: boolean
  isDeleted: boolean
  onReloadLatest: () => Promise<EventProfile | undefined>
}

function ProfileEditorForm({
  catalog,
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
  const api = useAdminApi()
  const framesQuery = useFrames()
  const frames = framesQuery.data
  // Until the frame list is here, stored selections stay as they are and can not be changed.
  const framesUnavailable = frames === undefined

  const [settings, setSettings] = useState<ProfileSettings>(() => initialSettings)
  const [currentRevision, setCurrentRevision] = useState<number>(() => initialRevision)
  const [isSaving, setIsSaving] = useState(false)
  // Saving while an image upload is in flight would store the previous asset id.
  const [uploading, setUploading] = useState({ logo: false, background: false })
  const extractMutation = useExtractTheme()
  // Saving mid-upload would store the previous asset; mid-extraction, the previous theme.
  const uploadPending = uploading.logo || uploading.background || extractMutation.isPending
  const [themeHistory, setThemeHistory] = useState<EventTheme[]>([])
  const [extractError, setExtractError] = useState<string | null>(null)
  const themeRef = useRef(initialSettings.theme)
  const [saveStatus, setSaveStatus] = useState<string | null>(null)
  const [clientErrors, setClientErrors] = useState<string[] | null>(null)
  const [serverErrors, setServerErrors] = useState<string[] | null>(null)
  const [conflictError, setConflictError] = useState<{
    message: string
    serverMessage?: string
  } | null>(null)

  useEffect(() => {
    themeRef.current = settings.theme // read by the extraction handler (an event, after render)
  }, [settings.theme])

  /** Apply a theme made from the background's colours; the previous theme can be restored. */
  const extractFrom = async (assetId: string) => {
    setExtractError(null)
    try {
      const extracted = await extractMutation.mutateAsync(assetId)
      const previous = themeRef.current
      setThemeHistory((history) => [...history, previous])
      setSettings((current) => ({
        ...current,
        theme: {
          tokens: extracted.tokens,
          source: 'extracted',
          preset: null,
          palette: extracted.palette,
        },
      }))
    } catch (err: unknown) {
      setExtractError(
        err instanceof AdminApiError
          ? `Colours could not be taken from the background: ${err.message}`
          : 'Colours could not be taken from the background.',
      )
    }
  }

  const undoExtraction = () => {
    const previous = themeHistory[themeHistory.length - 1]
    if (!previous) return
    setThemeHistory((history) => history.slice(0, -1))
    setSettings((current) => ({ ...current, theme: previous }))
  }

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
    if (uploadPending || isSaving) {
      return
    }
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
              placeholder="e.g. Chiang Mai Expo 2026"
              aria-describedby="help-profile-name"
              value={settings.name}
              onChange={(e) => setSettings((current) => ({ ...current, name: e.target.value }))}
              className={styles.input}
              disabled={isDeleted}
            />
            <p id="help-profile-name" className={styles.helperText}>
              Only admins see this name. It helps you find the profile later.
            </p>
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
              placeholder="e.g. Get ready for your photo!"
              value={settings.title}
              onChange={(e) => setSettings((current) => ({ ...current, title: e.target.value }))}
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
              placeholder="e.g. Look at the camera and strike a pose."
              value={settings.subtitle}
              onChange={(e) => setSettings((current) => ({ ...current, subtitle: e.target.value }))}
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
              placeholder="e.g. Start taking photos"
              value={settings.start_button_text}
              onChange={(e) => setSettings((current) => ({ ...current, start_button_text: e.target.value }))}
              className={styles.input}
              disabled={isDeleted}
            />
          </div>
        </section>

        <ThemeEditor
          theme={settings.theme}
          onChange={(theme) => setSettings((current) => ({ ...current, theme }))}
          catalog={catalog}
          hasBackground={Boolean(settings.background_asset_id)}
          extraction={{
            reextract: () => {
              if (settings.background_asset_id) void extractFrom(settings.background_asset_id)
            },
            undo: undoExtraction,
            canUndo: themeHistory.length > 0,
            pending: extractMutation.isPending,
            error: extractError,
          }}
          disabled={isDeleted}
        />

        {/* Images Section */}
        <section className={styles.formSection}>
          <h2 className={styles.sectionHeading}>Images</h2>
          <AssetPicker
            kind="logo"
            assetId={settings.logo_asset_id}
            onChange={(id) => setSettings((current) => ({ ...current, logo_asset_id: id }))}
            onUploadingChange={(active) => setUploading((u) => ({ ...u, logo: active }))}
            disabled={isDeleted || isSaving}
          />
          <AssetPicker
            kind="background"
            assetId={settings.background_asset_id}
            onChange={(id) => {
              const changed = id !== null && id !== settings.background_asset_id
              setSettings((current) => ({ ...current, background_asset_id: id }))
              // A new or replaced background proposes its own colours at once.
              if (changed) void extractFrom(id)
            }}
            onUploadingChange={(active) => setUploading((u) => ({ ...u, background: active }))}
            disabled={isDeleted || isSaving}
          />
          {uploadPending && (
            <p role="status" className={styles.readOnlyText}>
              Wait for image uploads to finish before saving.
            </p>
          )}
        </section>

        {/* Photo Layouts Section */}
        <section className={styles.formSection}>
          <h2 className={styles.sectionHeading}>Photo layouts</h2>
          <p id="help-layouts" className={styles.helperText}>
            Choose one or more print layouts guests can pick from.
          </p>
          {templates.map((tpl) => {
            const isChecked = settings.enabled_layouts.includes(tpl.key)
            const layoutFrames = frames?.filter((f) => f.template_key === tpl.key) ?? []
            const currentFrameId = settings.frame_selections?.[tpl.key] ?? ''
            const activeFrame = layoutFrames.find((f) => f.id === currentFrameId)

            return (
              <div key={tpl.key} className={styles.layoutItem}>
                <label className={styles.checkboxLabel}>
                  <input
                    type="checkbox"
                    value={tpl.key}
                    aria-describedby="help-layouts"
                    checked={isChecked}
                    onChange={(e) => {
                      const checked = e.target.checked
                      setSettings((current) => {
                        const nextLayouts = checked
                          ? [...current.enabled_layouts.filter((k) => k !== tpl.key), tpl.key]
                          : current.enabled_layouts.filter((k) => k !== tpl.key)
                        // Switching a layout on picks a matching built-in frame; switching it off
                        // drops its frame (the server refuses a frame for a layout that is off).
                        const fallback =
                          checked && frames && !current.frame_selections?.[tpl.key]
                            ? builtinFrameFor(frames, tpl.key, preferredFamily(current, frames, catalog))
                            : undefined
                        return {
                          ...current,
                          enabled_layouts: nextLayouts,
                          frame_selections: checked
                            ? {
                                ...current.frame_selections,
                                ...(fallback ? { [tpl.key]: fallback.id } : {}),
                              }
                            : withoutLayout(current.frame_selections, tpl.key),
                        }
                      })
                    }}
                    disabled={isDeleted}
                    className={styles.checkbox}
                  />
                  {tpl.name}
                </label>

                {isChecked && (
                  <div className={styles.frameChooser}>
                    <label htmlFor={`frame-for-${tpl.key}`} className={styles.label}>
                      Frame for {tpl.name}
                    </label>
                    <select
                      id={`frame-for-${tpl.key}`}
                      value={framesUnavailable ? currentFrameId : activeFrame ? activeFrame.id : ''}
                      onChange={(e) => {
                        const val = e.target.value
                        setSettings((current) => ({
                          ...current,
                          frame_selections: val
                            ? { ...current.frame_selections, [tpl.key]: val }
                            : withoutLayout(current.frame_selections, tpl.key),
                        }))
                      }}
                      className={styles.select}
                      disabled={isDeleted || framesUnavailable}
                    >
                      <option value="">No frame selected</option>
                      {framesUnavailable && currentFrameId && (
                        <option value={currentFrameId}>Saved frame (loading frames…)</option>
                      )}
                      {layoutFrames.some((f) => f.builtin) && (
                        <optgroup label="Built-in">
                          {layoutFrames
                            .filter((f) => f.builtin)
                            .map((frame) => (
                              <option key={frame.id} value={frame.id}>
                                {frame.name} (Built-in)
                              </option>
                            ))}
                        </optgroup>
                      )}
                      {layoutFrames.some((f) => !f.builtin) && (
                        <optgroup label="Your frames">
                          {layoutFrames
                            .filter((f) => !f.builtin)
                            .map((frame) => (
                              <option key={frame.id} value={frame.id}>
                                {frame.name}
                              </option>
                            ))}
                        </optgroup>
                      )}
                    </select>

                    {framesUnavailable && !framesQuery.isError && (
                      <p className={styles.helperText}>Loading frames…</p>
                    )}

                    {framesUnavailable && framesQuery.isError && (
                      <div role="alert" className={styles.alert}>
                        <p>
                          The frames could not be loaded, so this choice can not be changed right
                          now. Saving keeps the current frame.
                        </p>
                        <button
                          type="button"
                          onClick={() => {
                            void framesQuery.refetch()
                          }}
                          disabled={framesQuery.isFetching}
                        >
                          {framesQuery.isFetching ? 'Loading…' : 'Try again'}
                        </button>
                      </div>
                    )}

                    {!framesUnavailable && layoutFrames.length === 0 && (
                      <p className={styles.noFramesText}>
                        Upload a frame for this layout first.{' '}
                        <Link to="/admin/frames" className={styles.inlineLink}>
                          Frames
                        </Link>
                      </p>
                    )}

                    {!activeFrame && !(framesUnavailable && currentFrameId) && (
                      <p className={styles.missingFrameWarning} data-testid="missing-frame-warning">
                        No frame selected for {tpl.name}. Photos will print without a frame.
                      </p>
                    )}

                    {activeFrame?.builtin && (
                      <p className={styles.helperText}>
                        Built-in frame. Upload your own under Frames to use a different design.
                      </p>
                    )}

                    {activeFrame && (
                      <RetryingImage
                        src={api.framePreviewUrl(activeFrame.id, 1, activeFrame.sha256)}
                        alt={`${tpl.name} frame preview`}
                        className={styles.framePreviewThumbnail}
                      />
                    )}
                  </div>
                )}
              </div>
            )
          })}
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
              aria-describedby="help-mirror"
              checked={settings.mirror}
              onChange={(e) => setSettings((current) => ({ ...current, mirror: e.target.checked }))}
              disabled={isDeleted}
              className={styles.checkbox}
            />
            Mirror the camera preview
          </label>
          <p id="help-mirror" className={styles.helperText}>
            When on, the live camera preview works like a mirror.
          </p>

          <div className={styles.field}>
            <label htmlFor="field-inactivity-timeout" className={styles.label}>
              Inactivity timeout (seconds)
            </label>
            <input
              id="field-inactivity-timeout"
              type="number"
              min={INACTIVITY_LIMITS.min}
              max={INACTIVITY_LIMITS.max}
              placeholder="e.g. 120"
              aria-describedby="help-inactivity"
              // A cleared field is stored as 0 (still refused by validation) but shown empty so the
              // example placeholder is visible.
              value={settings.inactivity_timeout_s === 0 ? '' : settings.inactivity_timeout_s}
              onChange={(e) => {
                const num = parseInt(e.target.value, 10)
                setSettings((current) => ({
                  ...current,
                  inactivity_timeout_s: isNaN(num) ? 0 : num,
                }))
              }}
              className={styles.input}
              disabled={isDeleted}
            />
            <p id="help-inactivity" className={styles.helperText}>
              After this many seconds without a touch, the booth goes back to the start screen (30–900).
            </p>
          </div>

          <p className={styles.readOnlyText}>Countdown: 5 seconds before each photo</p>

          <fieldset
            className={styles.fieldset}
            disabled={isDeleted}
            aria-describedby="help-retakes"
          >
            <legend className={styles.legend}>Retakes</legend>
            <label className={styles.radioLabel}>
              <input
                type="radio"
                name="retake_mode"
                value="none"
                checked={settings.retake_mode === 'none'}
                onChange={() => setSettings((current) => ({ ...current, retake_mode: 'none' }))}
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
                onChange={() => setSettings((current) => ({ ...current, retake_mode: 'per_photo' }))}
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
                onChange={() => setSettings((current) => ({ ...current, retake_mode: 'all' }))}
                className={styles.radio}
              />
              Retake all photos
            </label>
          </fieldset>
          <p id="help-retakes" className={styles.helperText}>
            Choose whether guests may redo photos before their result is made.
          </p>

          <p className={styles.readOnlyText}>Delivery: QR code link on the local network</p>
        </section>

        <BigButton
          type="submit"
          disabled={isDeleted || isSaving || uploadPending}
          className={styles.saveButton}
        >
          Save profile
        </BigButton>
      </form>

      <div className={styles.previewColumn}>
        <EventPreview settings={settings} templates={templates} frames={frames} />
      </div>
    </div>
  )
}

export function ProfileEditorPage() {
  const { profileId } = useParams<{ profileId?: string }>()
  const isNew = !profileId

  const { data: templates, isLoading: isTemplatesLoading } = useTemplates()
  const catalogQuery = useThemeCatalog()
  const catalog = catalogQuery.data
  // Only a new profile needs the list here (its default frames); the form loads it itself.
  const framesQuery = useFrames(undefined, { enabled: isNew })
  // A new profile starts with built-in default frames, so it waits for the frame list (or its
  // failure, then it simply starts without frames).
  const framesSettled = framesQuery.data !== undefined || framesQuery.isError
  const {
    data: profile,
    isLoading: isProfileLoading,
    error: profileError,
    refetch: refetchProfile,
  } = useProfile(profileId)

  if (
    isTemplatesLoading ||
    catalogQuery.isLoading ||
    (!isNew && isProfileLoading) ||
    (isNew && !framesSettled)
  ) {
    return (
      <div className={styles.container}>
        <div className={styles.headerRow}>
          <h1 className={styles.heading}>{isNew ? 'New Event Profile' : 'Edit Event Profile'}</h1>
          <div className={styles.headerLinks}>
            <Link to="/admin/frames" className={styles.backLink}>
              Frames
            </Link>
            <Link to="/admin" className={styles.backLink}>
              Back to profiles
            </Link>
          </div>
        </div>
        <p>Loading…</p>
      </div>
    )
  }

  if (!templates || !catalog) {
    return (
      <div className={styles.container}>
        <div className={styles.headerRow}>
          <h1 className={styles.heading}>{isNew ? 'New Event Profile' : 'Edit Event Profile'}</h1>
          <div className={styles.headerLinks}>
            <Link to="/admin/frames" className={styles.backLink}>
              Frames
            </Link>
            <Link to="/admin" className={styles.backLink}>
              Back to profiles
            </Link>
          </div>
        </div>
        <div role="alert" className={styles.alert}>
          {templates ? 'Unable to load the event themes.' : 'Unable to load templates.'}
          <button
            type="button"
            onClick={() => {
              void catalogQuery.refetch()
            }}
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  if (!isNew && (profileError !== null || profile === undefined)) {
    return (
      <div className={styles.container}>
        <div className={styles.headerRow}>
          <h1 className={styles.heading}>Edit Event Profile</h1>
          <div className={styles.headerLinks}>
            <Link to="/admin/frames" className={styles.backLink}>
              Frames
            </Link>
            <Link to="/admin" className={styles.backLink}>
              Back to profiles
            </Link>
          </div>
        </div>
        <div role="alert" className={styles.alert}>
          Profile not found or could not be loaded.
        </div>
      </div>
    )
  }

  // Narrowed above: an existing profile is loaded whenever this is not a new one.
  const loaded = isNew ? undefined : profile
  const defaultPreset =
    catalog.presets.find((p) => p.id === catalog.default_preset) ?? catalog.presets[0]
  const defaultFrames = Object.fromEntries(
    templates.flatMap((t) => {
      const frame = builtinFrameFor(framesQuery.data ?? [], t.key, defaultPreset?.frame_family ?? 'midnight')
      return frame ? [[t.key, frame.id]] : []
    }),
  )
  const initialSettings =
    loaded?.settings ??
    newProfileSettings(
      templates.map((t) => t.key),
      defaultPreset ? presetTheme(defaultPreset) : { tokens: {}, source: 'custom', preset: null, palette: [] },
      defaultFrames,
    )
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
        <div className={styles.headerLinks}>
          <Link to="/admin/frames" className={styles.backLink}>
            Frames
          </Link>
          <Link to="/admin" className={styles.backLink}>
            Back to profiles
          </Link>
        </div>
      </div>

      <ProfileEditorForm
        key={loaded?.id ?? 'new'}
        catalog={catalog}
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
