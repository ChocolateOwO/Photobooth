import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link } from 'react-router'

import {
  AdminApiError,
  FRAME_LIMITS,
  type Frame,
  type TemplateSummary,
} from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import {
  useDeleteFrame,
  useFrames,
  useRenameFrame,
  useReplaceFrameFile,
  useTemplates,
  useTemplateSpec,
  useUploadFrame,
} from '../api/hooks'
import { RetryingImage } from '../components/RetryingImage'
import styles from './FrameManagerPage.module.css'

interface FrameCardItemProps {
  frame: Frame
  onReplaceFile: (id: string, file: File) => Promise<void>
  onRename: (id: string, name: string) => Promise<void>
  onDeleteRequest: (frame: Frame) => void
  onClientError: (msg: string | null) => void
  onServerErrors: (msgs: string[] | null) => void
  onClearStatus: () => void
}

function FrameCardItem({
  frame,
  onReplaceFile,
  onRename,
  onDeleteRequest,
  onClientError,
  onServerErrors,
  onClearStatus,
}: FrameCardItemProps) {
  const api = useAdminApi()
  const [isRenaming, setIsRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(frame.name)
  const [isSavingRename, setIsSavingRename] = useState(false)
  const replaceInputRef = useRef<HTMLInputElement>(null)

  const handleReplaceFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    onClientError(null)
    onServerErrors(null)
    onClearStatus()

    if (file.type !== 'image/png') {
      onClientError('The frame must be a PNG file.')
      e.target.value = ''
      return
    }
    if (file.size > FRAME_LIMITS.maxBytes) {
      onClientError('The frame must be 10 MB or smaller.')
      e.target.value = ''
      return
    }

    try {
      await onReplaceFile(frame.id, file)
    } finally {
      e.target.value = ''
    }
  }

  const handleSaveRename = async () => {
    const trimmed = renameValue.trim()
    if (!trimmed) {
      onClientError('Enter a frame name.')
      return
    }
    setIsSavingRename(true)
    onClientError(null)
    onServerErrors(null)
    onClearStatus()
    try {
      await onRename(frame.id, trimmed)
      setIsRenaming(false)
    } finally {
      setIsSavingRename(false)
    }
  }

  const handleCancelRename = () => {
    setIsRenaming(false)
    setRenameValue(frame.name)
    onClientError(null)
  }

  return (
    <li data-testid="frame-card" className={styles.frameCard}>
      <div className={styles.frameHeader}>
        <h3 className={styles.frameName}>{frame.name}</h3>
        {frame.builtin && <span className={styles.builtinBadge}>Built-in</span>}
        <span className={styles.dimensions}>
          {frame.width} × {frame.height} px
        </span>
      </div>

      <div className={styles.imagesGrid}>
        <div className={styles.imageColumn}>
          <div className={styles.checkerboard}>
            <img
              src={api.frameContentUrl(frame.id, frame.sha256)}
              alt={`${frame.name} frame file`}
              loading="lazy"
              className={styles.frameImage}
            />
          </div>
        </div>

        <div className={styles.imageColumn}>
          <figure className={styles.figure}>
            <RetryingImage
              src={api.framePreviewUrl(frame.id, 1, frame.sha256)}
              alt={`${frame.name} sample output`}
              className={styles.previewImage}
            />
            <figcaption className={styles.caption}>
              Sample output with placeholder photos
            </figcaption>
          </figure>
        </div>
      </div>

      {frame.warnings && frame.warnings.length > 0 && (
        <div className={styles.warningsList}>
          {frame.warnings.map((warning, idx) => (
            <p key={idx} className={styles.warningText}>
              {warning}
            </p>
          ))}
        </div>
      )}

      <div className={styles.cardActions}>
        {frame.builtin ? (
          <p className={styles.builtinNote}>
            Ready to use. Built-in frames can not be replaced, renamed or deleted.
          </p>
        ) : isRenaming ? (
          <div className={styles.renameRow}>
            <div className={styles.renameField}>
              <label htmlFor={`rename-name-${frame.id}`} className={styles.label}>
                Frame name
              </label>
              <input
                id={`rename-name-${frame.id}`}
                type="text"
                maxLength={80}
                placeholder="e.g. Gold border"
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                className={styles.input}
                disabled={isSavingRename}
              />
            </div>
            <div className={styles.renameButtons}>
              <button
                type="button"
                onClick={() => {
                  void handleSaveRename()
                }}
                disabled={isSavingRename}
                className={styles.saveButton}
              >
                Save name
              </button>
              <button
                type="button"
                onClick={handleCancelRename}
                disabled={isSavingRename}
                className={styles.cancelButton}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className={styles.actionButtons}>
            <button
              type="button"
              onClick={() => replaceInputRef.current?.click()}
              className={styles.actionButton}
            >
              Replace file for {frame.name}
            </button>
            <input
              ref={replaceInputRef}
              type="file"
              accept="image/png"
              aria-label={`Replace file for ${frame.name}`}
              onChange={(e) => {
                void handleReplaceFileChange(e)
              }}
              className={styles.visuallyHidden}
            />
            <button
              type="button"
              onClick={() => {
                setRenameValue(frame.name)
                setIsRenaming(true)
              }}
              className={styles.actionButton}
            >
              Rename {frame.name}
            </button>
            <button
              type="button"
              onClick={() => onDeleteRequest(frame)}
              className={styles.deleteButton}
            >
              Delete {frame.name}
            </button>
          </div>
        )}
      </div>
    </li>
  )
}

type FramesState = 'loading' | 'error' | 'ready'

interface TemplateFrameSectionProps {
  template: TemplateSummary
  frames: Frame[]
  framesState: FramesState
}

function TemplateFrameSection({ template, frames, framesState }: TemplateFrameSectionProps) {
  const api = useAdminApi()
  const { data: spec, isLoading: isSpecLoading } = useTemplateSpec(template.key)
  const uploadMutation = useUploadFrame()
  const replaceMutation = useReplaceFrameFile()
  const renameMutation = useRenameFrame()
  const deleteMutation = useDeleteFrame()

  const [frameName, setFrameName] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState<string | null>(null)
  const [clientError, setClientError] = useState<string | null>(null)
  const [serverErrors, setServerErrors] = useState<string[] | null>(null)
  const [frameToDelete, setFrameToDelete] = useState<Frame | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const builtinFrames = frames.filter((f) => f.builtin)
  const customFrames = frames.filter((f) => !f.builtin)

  const clearAlerts = () => {
    setClientError(null)
    setServerErrors(null)
  }

  const handleFileInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    clearAlerts()
    setUploadStatus(null)

    if (!file) {
      setSelectedFile(null)
      return
    }
    if (file.type !== 'image/png') {
      setClientError('The frame must be a PNG file.')
      setSelectedFile(null)
      e.target.value = ''
      return
    }
    if (file.size > FRAME_LIMITS.maxBytes) {
      setClientError('The frame must be 10 MB or smaller.')
      setSelectedFile(null)
      e.target.value = ''
      return
    }
    setSelectedFile(file)
  }

  const handleUploadSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (isUploading) return

    clearAlerts()
    setUploadStatus(null)

    const trimmedName = frameName.trim()
    if (!trimmedName) {
      setClientError('Enter a frame name.')
      return
    }
    if (!selectedFile) {
      setClientError('The frame must be a PNG file.')
      return
    }
    if (selectedFile.type !== 'image/png') {
      setClientError('The frame must be a PNG file.')
      return
    }
    if (selectedFile.size > FRAME_LIMITS.maxBytes) {
      setClientError('The frame must be 10 MB or smaller.')
      return
    }

    setIsUploading(true)
    try {
      await uploadMutation.mutateAsync({
        templateKey: template.key,
        name: trimmedName,
        file: selectedFile,
      })
      setFrameName('')
      setSelectedFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
      setUploadStatus(`${trimmedName} was added.`)
    } catch (err: unknown) {
      if (err instanceof AdminApiError) {
        setServerErrors(err.messages.length > 0 ? err.messages : [err.message])
      } else if (err instanceof Error) {
        setServerErrors([err.message])
      } else {
        setServerErrors(['Upload failed.'])
      }
    } finally {
      setIsUploading(false)
    }
  }

  const handleReplaceFile = async (id: string, file: File) => {
    clearAlerts()
    setUploadStatus(null)
    try {
      await replaceMutation.mutateAsync({ id, file })
    } catch (err: unknown) {
      if (err instanceof AdminApiError) {
        setServerErrors(err.messages.length > 0 ? err.messages : [err.message])
      } else if (err instanceof Error) {
        setServerErrors([err.message])
      } else {
        setServerErrors(['Replace failed.'])
      }
    }
  }

  const handleRename = async (id: string, name: string) => {
    clearAlerts()
    setUploadStatus(null)
    try {
      await renameMutation.mutateAsync({ id, name })
    } catch (err: unknown) {
      if (err instanceof AdminApiError) {
        setServerErrors(err.messages.length > 0 ? err.messages : [err.message])
      } else if (err instanceof Error) {
        setServerErrors([err.message])
      } else {
        setServerErrors(['Rename failed.'])
      }
      throw err
    }
  }

  const handleDeleteRequest = (frame: Frame) => {
    clearAlerts()
    setUploadStatus(null)
    setFrameToDelete(frame)
  }

  const handleConfirmDelete = async () => {
    if (!frameToDelete) return
    setIsDeleting(true)
    clearAlerts()
    setUploadStatus(null)
    try {
      await deleteMutation.mutateAsync(frameToDelete.id)
      setFrameToDelete(null)
    } catch (err: unknown) {
      setFrameToDelete(null)
      if (err instanceof AdminApiError) {
        setServerErrors(err.messages.length > 0 ? err.messages : [err.message])
      } else if (err instanceof Error) {
        setServerErrors([err.message])
      } else {
        setServerErrors(['Delete failed.'])
      }
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <section className={styles.templateSection}>
      <h2 className={styles.sectionHeading}>{template.name}</h2>

      {isSpecLoading ? (
        <p className={styles.loadingText}>Loading requirements…</p>
      ) : spec && spec.frame_requirements && spec.frame_requirements.length > 0 ? (
        <ul className={styles.requirementsList}>
          {spec.frame_requirements.map((req, idx) => (
            <li key={idx}>{req}</li>
          ))}
        </ul>
      ) : null}

      <div className={styles.downloadLinks}>
        <a
          href={api.templateGuideUrl(template.key)}
          download
          className={styles.downloadLink}
        >
          Download guide image
        </a>
        <a
          href={api.templateBlankUrl(template.key)}
          download
          className={styles.downloadLink}
        >
          Download blank canvas
        </a>
      </div>

      <form onSubmit={(e) => void handleUploadSubmit(e)} className={styles.uploadForm}>
        <div className={styles.field}>
          <label htmlFor={`frame-name-${template.key}`} className={styles.label}>
            Frame name
          </label>
          <input
            id={`frame-name-${template.key}`}
            type="text"
            maxLength={80}
            placeholder="e.g. Gold border"
            value={frameName}
            onChange={(e) => {
              setFrameName(e.target.value)
              setClientError(null)
            }}
            className={styles.input}
            disabled={isUploading}
          />
        </div>

        <div className={styles.field}>
          <label htmlFor={`frame-file-${template.key}`} className={styles.label}>
            Frame PNG file
          </label>
          <input
            id={`frame-file-${template.key}`}
            ref={fileInputRef}
            type="file"
            accept="image/png"
            onChange={handleFileInputChange}
            className={styles.fileInput}
            disabled={isUploading}
          />
        </div>

        <button
          type="submit"
          disabled={isUploading}
          className={styles.uploadButton}
        >
          {isUploading ? 'Uploading…' : 'Upload frame'}
        </button>
      </form>

      {uploadStatus && (
        <div role="status" className={styles.status}>
          {uploadStatus}
        </div>
      )}

      {(clientError !== null || (serverErrors !== null && serverErrors.length > 0)) && (
        <div role="alert" className={styles.alert}>
          {clientError !== null && <p className={styles.alertMessage}>{clientError}</p>}
          {serverErrors?.map((msg, idx) => (
            <p key={idx} className={styles.alertMessage}>
              {msg}
            </p>
          ))}
        </div>
      )}

      {framesState === 'ready' && builtinFrames.length > 0 && (
        <>
          <h3 className={styles.listHeading}>Built-in frames</h3>
          <ul className={styles.framesList} aria-label={`Built-in frames for ${template.name}`}>
            {builtinFrames.map((frame) => (
              <FrameCardItem
                key={frame.id}
                frame={frame}
                onReplaceFile={handleReplaceFile}
                onRename={handleRename}
                onDeleteRequest={handleDeleteRequest}
                onClientError={setClientError}
                onServerErrors={setServerErrors}
                onClearStatus={() => setUploadStatus(null)}
              />
            ))}
          </ul>
        </>
      )}

      {framesState === 'ready' && <h3 className={styles.listHeading}>Your frames</h3>}
      {framesState === 'loading' ? (
        <p className={styles.loadingText}>Loading frames…</p>
      ) : framesState === 'error' ? null : customFrames.length === 0 ? (
        <p className={styles.emptyText}>No frames uploaded for this layout yet.</p>
      ) : (
        <ul className={styles.framesList} aria-label={`Your frames for ${template.name}`}>
          {customFrames.map((frame) => (
            <FrameCardItem
              key={frame.id}
              frame={frame}
              onReplaceFile={handleReplaceFile}
              onRename={handleRename}
              onDeleteRequest={handleDeleteRequest}
              onClientError={(msg) => {
                clearAlerts()
                setClientError(msg)
              }}
              onServerErrors={(msgs) => {
                clearAlerts()
                setServerErrors(msgs)
              }}
              onClearStatus={() => setUploadStatus(null)}
            />
          ))}
        </ul>
      )}

      {frameToDelete && (
        <div className={styles.dialogOverlay}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`delete-heading-${frameToDelete.id}`}
            className={styles.dialog}
          >
            <h3
              id={`delete-heading-${frameToDelete.id}`}
              className={styles.dialogHeading}
            >
              Delete {frameToDelete.name}?
            </h3>
            <p className={styles.dialogText}>
              The file is removed from this booth. Event Profiles that use it must pick another frame first.
            </p>
            <div className={styles.dialogButtons}>
              <button
                type="button"
                onClick={() => {
                  void handleConfirmDelete()
                }}
                disabled={isDeleting}
                className={styles.deleteConfirmButton}
              >
                Delete frame
              </button>
              <button
                type="button"
                onClick={() => setFrameToDelete(null)}
                disabled={isDeleting}
                className={styles.cancelButton}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

export function FrameManagerPage() {
  const { data: templates, isLoading: templatesLoading, error: templatesError } = useTemplates()
  const framesQuery = useFrames()
  const allFrames = framesQuery.data
  // A failed or unfinished frame list must never look like "no frames uploaded".
  const framesState: FramesState = allFrames
    ? 'ready'
    : framesQuery.isError
      ? 'error'
      : 'loading'

  return (
    <div className={styles.container}>
      <header className={styles.headerRow}>
        <h1 className={styles.heading}>Frames</h1>
        <Link to="/admin" className={styles.backLink}>
          Event Profiles
        </Link>
      </header>

      <p className={styles.introText}>
        Design frames in your own software, then upload the finished PNG here. This app never edits your file.
      </p>

      {templatesLoading && <p className={styles.loadingText}>Loading…</p>}

      {templatesError && (
        <div role="alert" className={styles.alert}>
          Unable to load templates.
        </div>
      )}

      {framesState === 'error' && (
        <div role="alert" className={styles.alert}>
          <p className={styles.alertMessage}>The uploaded frames could not be loaded.</p>
          <button
            type="button"
            onClick={() => {
              void framesQuery.refetch()
            }}
            disabled={framesQuery.isFetching}
            className={styles.actionButton}
          >
            {framesQuery.isFetching ? 'Loading…' : 'Try again'}
          </button>
        </div>
      )}

      {templates && (
        <div className={styles.sectionsList}>
          {templates.map((tpl) => {
            const templateFrames = allFrames?.filter((f) => f.template_key === tpl.key) ?? []
            return (
              <TemplateFrameSection
                key={tpl.key}
                template={tpl}
                frames={templateFrames}
                framesState={framesState}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}
