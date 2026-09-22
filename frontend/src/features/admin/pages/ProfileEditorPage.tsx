import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'

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
import { AvailableFramesEditor } from '../components/AvailableFramesEditor'
import { EventPreview } from '../components/EventPreview'
import { ThemeEditor } from '../components/ThemeEditor'
import { PillButton } from '../components/ui/Controls'
import { MessageDialog } from '../components/ui/MessageDialog'
import styles from './ProfileEditorPage.module.css'

interface FieldProblem {
  fieldId: string
  message: string
}

/** Everything that blocks saving, in form order, each with the field that fixes it. */
function validateSettings(settings: ProfileSettings): FieldProblem[] {
  const problems: FieldProblem[] = []
  if (!settings.name.trim()) {
    problems.push({ fieldId: 'field-profile-name', message: 'Profile name is required.' })
  }
  if (!settings.title.trim()) {
    problems.push({ fieldId: 'field-title', message: 'Title is required.' })
  }
  if (
    isNaN(settings.inactivity_timeout_s) ||
    settings.inactivity_timeout_s < INACTIVITY_LIMITS.min ||
    settings.inactivity_timeout_s > INACTIVITY_LIMITS.max
  ) {
    problems.push({
      fieldId: 'field-inactivity-timeout',
      message: `Inactivity timeout must be between ${INACTIVITY_LIMITS.min} and ${INACTIVITY_LIMITS.max} seconds.`,
    })
  }
  return problems
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
  const framesQuery = useFrames()
  const frames = framesQuery.data

  const [settings, setSettings] = useState<ProfileSettings>(() => initialSettings)
  const [currentRevision, setCurrentRevision] = useState<number>(() => initialRevision)
  const [isSaving, setIsSaving] = useState(false)
  // Saving while an image upload is in flight would store the previous asset id.
  const [uploading, setUploading] = useState({ logo: false, background: false })
  const extractMutation = useExtractTheme()
  // Every extraction gets a number; a theme edit or a newer background invalidates older ones, so
  // a late answer never overwrites a newer choice (P5R-002).
  const extractionSeq = useRef(0)
  const [pendingExtraction, setPendingExtraction] = useState<number | null>(null)
  // Saving mid-upload would store the previous asset; mid-extraction, the previous theme.
  const uploadPending = uploading.logo || uploading.background || pendingExtraction !== null
  const [themeHistory, setThemeHistory] = useState<EventTheme[]>([])
  const [extractError, setExtractError] = useState<string | null>(null)
  const themeRef = useRef(initialSettings.theme)
  const location = useLocation()
  // A newly created profile arrives here with its "saved" result to show.
  const [saved, setSaved] = useState(() => (location.state as { saved?: boolean } | null)?.saved === true)
  const [attempted, setAttempted] = useState(false)
  const [showProblems, setShowProblems] = useState(false)
  const [serverErrors, setServerErrors] = useState<string[] | null>(null)
  const [conflictError, setConflictError] = useState<{
    message: string
    serverMessage?: string
  } | null>(null)

  useEffect(() => {
    themeRef.current = settings.theme // read by the extraction handler (an event, after render)
  }, [settings.theme])

  // A new profile whose frame list arrives late still starts with every built-in frame.
  const [defaultsApplied, setDefaultsApplied] = useState(!isNew || frames !== undefined)
  if (!defaultsApplied && frames) {
    setDefaultsApplied(true)
    setSettings((current) =>
      current.available_frames.length > 0
        ? current
        : { ...current, available_frames: frames.filter((f) => f.builtin).map((f) => f.id) },
    )
  }

  const invalidateExtraction = () => {
    extractionSeq.current += 1
    setPendingExtraction(null)
  }

  /** Apply a theme made from the background's colours; the previous theme can be restored. */
  const extractFrom = async (assetId: string) => {
    extractionSeq.current += 1
    const seq = extractionSeq.current
    setPendingExtraction(seq)
    setExtractError(null)
    try {
      const extracted = await extractMutation.mutateAsync(assetId)
      if (extractionSeq.current !== seq) return // a newer background or a theme edit came first
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
      if (extractionSeq.current !== seq) return
      setExtractError(
        err instanceof AdminApiError
          ? `Colours could not be taken from the background: ${err.message}`
          : 'Colours could not be taken from the background.',
      )
    } finally {
      setPendingExtraction((pending) => (pending === seq ? null : pending))
    }
  }

  const undoExtraction = () => {
    const previous = themeHistory[themeHistory.length - 1]
    if (!previous) return
    invalidateExtraction()
    setThemeHistory((history) => history.slice(0, -1))
    setSettings((current) => ({ ...current, theme: previous }))
  }

  // Wide screens: the editor fills the window below the header; the form scrolls in its own
  // column and the preview column stays exactly where it is. The layout's distance from the top
  // of the page (header height) is measured, since it changes when the header wraps.
  const layoutRef = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const measure = () => {
      const layout = layoutRef.current
      if (!layout) return
      const top = layout.getBoundingClientRect().top + window.scrollY
      layout.style.setProperty('--editor-top', `${Math.round(top)}px`)
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  // Every problem at once, each tied to the field that fixes it.
  const problems = validateSettings(settings)
  const invalid = new Map(attempted ? problems.map((p) => [p.fieldId, p.message]) : [])
  const fieldProps = (fieldId: string, helpId?: string) => {
    const message = invalid.get(fieldId)
    const describedBy = [helpId, message ? `${fieldId}-error` : undefined].filter(Boolean).join(' ')
    return {
      'aria-invalid': message ? true : undefined,
      'aria-describedby': describedBy || undefined,
      'data-invalid': message ? '' : undefined,
    }
  }
  const fieldError = (fieldId: string) => {
    const message = invalid.get(fieldId)
    return message ? (
      <p id={`${fieldId}-error`} className={styles.fieldError}>
        {message}
      </p>
    ) : null
  }

  /** Moves to a field after a dialog closed (so the dialog's own focus handling is done). */
  const goToField = (fieldId: string | undefined) => {
    if (!fieldId) return
    window.setTimeout(() => {
      const field = document.getElementById(fieldId)
      field?.scrollIntoView?.({ block: 'center' })
      field?.focus({ preventScroll: true })
    }, 0)
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (uploadPending || isSaving) {
      return
    }
    setSaved(false)
    setServerErrors(null)
    setConflictError(null)

    if (problems.length > 0) {
      setAttempted(true)
      setShowProblems(true)
      return
    }

    setIsSaving(true)
    try {
      if (isNew) {
        // Frame list never loaded: leave it out, so the server offers every built-in frame
        // instead of saving an empty list by accident (P5R2-001).
        const { available_frames: draftFrames, ...rest } = settings
        const created = await createMutation.mutateAsync(
          defaultsApplied ? { ...rest, available_frames: draftFrames } : rest,
        )
        void navigate(`/admin/profiles/${created.id}`, { state: { saved: true } })
      } else if (profileId) {
        const updated = await updateMutation.mutateAsync({
          id: profileId,
          settings,
          revision: currentRevision,
        })
        setCurrentRevision(updated.revision)
        setSaved(true)
      }
    } catch (err: unknown) {
      // A stale revision offers a reload; other conflicts (a name already in use) are plain
      // save failures with the server's reason.
      const stale =
        err instanceof AdminApiError &&
        err.kind === 'conflict' &&
        err.messages.concat(err.message).some((m) => m.includes('changed elsewhere'))
      if (stale) {
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
      setAttempted(false)
      setSaved(false)
    }
  }

  return (
    <div className={styles.editorLayout} ref={layoutRef}>
      <form onSubmit={handleSubmit} className={styles.formColumn} noValidate>
        {isDeleted && (
          <div role="alert" className={styles.alert}>
            This profile is deleted. Restore it from the list to edit.
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
              {...fieldProps('field-profile-name', 'help-profile-name')}
              value={settings.name}
              onChange={(e) => setSettings((current) => ({ ...current, name: e.target.value }))}
              className={styles.input}
              disabled={isDeleted}
            />
            {fieldError('field-profile-name')}
            <p id="help-profile-name" className={styles.helperText}>
              Only admins see this name. It helps you find the profile later.
            </p>
          </div>
        </section>

        {/* Start screen and booth texts */}
        <section className={styles.formSection}>
          <h2 className={styles.sectionHeading}>Start screen</h2>
          <p className={styles.helperText}>
            The start screen shows only the background, the logo and the Start button. The title and
            subtitle are kept with the profile for the later booth screens.
          </p>
          <div className={styles.field}>
            <label htmlFor="field-title" className={styles.label}>
              Title
            </label>
            <input
              id="field-title"
              type="text"
              maxLength={TEXT_LIMITS.title}
              placeholder="e.g. Get ready for your photo!"
              {...fieldProps('field-title')}
              value={settings.title}
              onChange={(e) => setSettings((current) => ({ ...current, title: e.target.value }))}
              className={styles.input}
              disabled={isDeleted}
            />
            {fieldError('field-title')}
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
          onChange={(theme) => {
            invalidateExtraction() // the admin's own choice wins over a pending extraction
            setSettings((current) => ({ ...current, theme }))
          }}
          catalog={catalog}
          hasBackground={Boolean(settings.background_asset_id)}
          extraction={{
            reextract: () => {
              if (settings.background_asset_id) void extractFrom(settings.background_asset_id)
            },
            undo: undoExtraction,
            canUndo: themeHistory.length > 0,
            pending: pendingExtraction !== null,
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
              // A new or replaced background proposes its own colours at once; a removed one
              // cancels any pending proposal.
              if (changed) void extractFrom(id)
              else if (id === null) invalidateExtraction()
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

        <AvailableFramesEditor
          frames={frames}
          loadFailed={framesQuery.isError}
          onRetry={() => {
            void framesQuery.refetch()
          }}
          templates={templates}
          available={settings.available_frames}
          onChange={(ids) => setSettings((current) => ({ ...current, available_frames: ids }))}
          allowSurprise={settings.allow_surprise_me}
          onSurpriseChange={(allow) =>
            setSettings((current) => ({ ...current, allow_surprise_me: allow }))
          }
          unloadedNote={
            isNew
              ? 'Saving offers every built-in frame; you can change the list once the frames load.'
              : 'Saving keeps the current list.'
          }
          disabled={isDeleted}
        />

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
              {...fieldProps('field-inactivity-timeout', 'help-inactivity')}
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
            {fieldError('field-inactivity-timeout')}
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

      <div className={styles.previewColumn} data-testid="preview-column">
        <EventPreview settings={settings} templates={templates} frames={frames} />
      </div>

      {showProblems && problems.length > 0 && (
        <MessageDialog
          kind="warning"
          title="Some information is missing or invalid"
          testId="problems-dialog"
          restoreFocus={false}
          onClose={() => {
            setShowProblems(false)
            goToField(problems[0]?.fieldId)
          }}
          actions={
            <PillButton
              tone="primary"
              onClick={() => {
                setShowProblems(false)
                goToField(problems[0]?.fieldId)
              }}
            >
              Go to first problem
            </PillButton>
          }
        >
          <p>Fix {problems.length === 1 ? 'this' : `these ${problems.length} things`} before saving:</p>
          <ul>
            {problems.map((problem) => (
              <li key={problem.fieldId}>{problem.message}</li>
            ))}
          </ul>
        </MessageDialog>
      )}
      {saved && (
        <MessageDialog
          kind="success"
          title="Saved"
          autoCloseMs={2500}
          testId="saved-dialog"
          onClose={() => {
            setSaved(false)
            if (location.state) void navigate('.', { replace: true, state: null })
          }}
        >
          <p>Profile saved successfully.</p>
        </MessageDialog>
      )}
      {serverErrors && serverErrors.length > 0 && (
        <MessageDialog kind="error" title="The profile was not saved" onClose={() => setServerErrors(null)}>
          <ul>
            {serverErrors.map((err) => (
              <li key={err}>{err}</li>
            ))}
          </ul>
        </MessageDialog>
      )}
      {conflictError && (
        <MessageDialog
          kind="warning"
          title="Changed somewhere else"
          onClose={() => setConflictError(null)}
          actions={
            <PillButton
              tone="primary"
              onClick={() => {
                void handleReloadLatest()
              }}
            >
              Reload latest
            </PillButton>
          }
        >
          <p>{conflictError.message}</p>
          {conflictError.serverMessage && <p>{conflictError.serverMessage}</p>}
        </MessageDialog>
      )}
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
  // Once the form is shown it stays mounted, even while the list is fetched again (P5R-003).
  const [formReady, setFormReady] = useState(false)
  if (!formReady && framesSettled) setFormReady(true)
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
    (isNew && !framesSettled && !formReady)
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
  // A new profile offers every built-in frame (uploads are switched on by the admin).
  const builtinIds = (framesQuery.data ?? []).filter((f) => f.builtin).map((f) => f.id)
  const initialSettings =
    loaded?.settings ??
    newProfileSettings(
      defaultPreset
        ? presetTheme(defaultPreset)
        : { tokens: {}, source: 'custom', preset: null, palette: [] },
      builtinIds,
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
