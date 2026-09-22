import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link } from 'react-router'

import {
  AdminApiError,
  FRAME_LIMITS,
  type Frame,
  type TemplateSummary,
} from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import { RetryingImage } from '../../../shared/ui/RetryingImage'
import {
  useDeleteFrame,
  useFrames,
  useRenameFrame,
  useReplaceFrameFile,
  useTemplates,
  useTemplateSpec,
  useUploadFrame,
} from '../api/hooks'
import { IconButton, PillButton, PillGroup } from '../components/ui/Controls'
import { MessageDialog } from '../components/ui/MessageDialog'
import { Modal } from '../components/ui/Modal'
import { layoutLabel } from '../frameCatalog'
import styles from './FrameManagerPage.module.css'

type FramesState = 'loading' | 'error' | 'ready'

type Message = { kind: 'success' | 'error'; title: string; lines: string[] }

type Dialog =
  | { type: 'layout-details'; template: TemplateSummary }
  | { type: 'layout-preview'; template: TemplateSummary }
  | { type: 'frame-preview'; frame: Frame }
  | { type: 'frame-details'; frame: Frame }
  | { type: 'upload' }
  | { type: 'rename'; frame: Frame }
  | { type: 'delete'; frame: Frame }

function errorLines(err: unknown, fallback: string): string[] {
  if (err instanceof AdminApiError) return err.messages.length > 0 ? err.messages : [err.message]
  if (err instanceof Error) return [err.message]
  return [fallback]
}

/** Refuses what the server would refuse anyway, before anything is sent. */
function fileProblem(file: File): string | null {
  if (file.type !== FRAME_LIMITS.mime) return 'The frame must be a PNG file.'
  if (file.size > FRAME_LIMITS.maxBytes) return 'The frame must be 10 MB or smaller.'
  return null
}

function inches(value: number): string {
  return `${value}`
}

function megabytes(bytes: number): string {
  return `${Math.round((bytes / (1024 * 1024)) * 10) / 10} MB`
}

function kilobytes(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : megabytes(bytes)
}

/* ---------- layouts ---------- */

function LayoutRow({
  template,
  onDetails,
  onPreview,
}: {
  template: TemplateSummary
  onDetails: () => void
  onPreview: () => void
}) {
  return (
    <li className={styles.layoutRow} data-testid="layout-row">
      <span className={styles.layoutName}>{template.name}</span>
      <span className={styles.layoutMeta}>
        {inches(template.width_in)} × {inches(template.height_in)} in
      </span>
      <span className={styles.layoutMeta}>
        {template.width_px} × {template.height_px} px
      </span>
      <span className={styles.rowActions}>
        <IconButton icon="details" label={`Details of ${template.name}`} onClick={onDetails} />
        <IconButton icon="preview" label={`Preview of ${template.name}`} onClick={onPreview} />
      </span>
    </li>
  )
}

function GuideLink({ template }: { template: TemplateSummary }) {
  const api = useAdminApi()
  return (
    <a href={api.templateGuideUrl(template.key)} download className={styles.linkPill}>
      Download guide image
    </a>
  )
}

function rect(r: { x: number; y: number; w: number; h: number }): string {
  return `x ${r.x}, y ${r.y}, ${r.w} × ${r.h} px`
}

function LayoutDetailsDialog({ template, onClose }: { template: TemplateSummary; onClose: () => void }) {
  const { data: spec, isLoading, isError } = useTemplateSpec(template.key)
  return (
    <Modal
      title={`${template.name}: specification`}
      onClose={onClose}
      size="large"
      testId="layout-details"
      footer={<GuideLink template={template} />}
    >
      {isLoading && <p>Loading the specification…</p>}
      {isError && <p role="alert">The specification could not be loaded.</p>}
      {spec && (
        <>
          <dl className={styles.specList}>
            <dt>Physical size</dt>
            <dd>
              {inches(spec.width_in)} × {inches(spec.height_in)} in ({spec.orientation})
            </dd>
            <dt>Pixels</dt>
            <dd>
              {spec.width_px} × {spec.height_px} px
            </dd>
            <dt>Resolution</dt>
            <dd>{spec.dpi} DPI</dd>
            <dt>File</dt>
            <dd>
              {spec.frame_rules.format} with transparency ({spec.frame_rules.mode}),{' '}
              {spec.frame_rules.color}, {spec.frame_rules.animated ? 'may be animated' : 'not animated'}
              {spec.frame_rules.exact_size ? ', exactly this pixel size' : ''}
            </dd>
            <dt>Photo areas</dt>
            <dd>At least {Math.round(spec.frame_rules.slot_min_transparency * 100)}% transparent</dd>
            <dt>Maximum file size</dt>
            <dd>{megabytes(spec.frame_rules.max_bytes)}</dd>
            <dt>Safe area</dt>
            <dd>{rect(spec.safe_area)}</dd>
            <dt>Branding area</dt>
            <dd>{spec.branding_area ? rect(spec.branding_area) : 'None'}</dd>
            <dt>Photos</dt>
            <dd>
              {spec.captures_per_session} per session, {spec.photos_per_output} per output,{' '}
              {spec.outputs_per_session} {spec.outputs_per_session === 1 ? 'output' : 'outputs'}
            </dd>
          </dl>
          <table className={styles.slotTable}>
            <caption>Photo slot coordinates (px)</caption>
            <thead>
              <tr>
                <th scope="col">Photo</th>
                <th scope="col">x</th>
                <th scope="col">y</th>
                <th scope="col">Width</th>
                <th scope="col">Height</th>
                <th scope="col">Aspect</th>
              </tr>
            </thead>
            <tbody>
              {spec.slots.map((slot) => (
                <tr key={slot.index}>
                  <th scope="row">{slot.index}</th>
                  <td>{slot.x}</td>
                  <td>{slot.y}</td>
                  <td>{slot.w}</td>
                  <td>{slot.h}</td>
                  <td>{slot.aspect}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {spec.frame_requirements.length > 0 && (
            <ul className={styles.requirements}>
              {spec.frame_requirements.map((req) => (
                <li key={req}>{req}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </Modal>
  )
}

function LayoutPreviewDialog({ template, onClose }: { template: TemplateSummary; onClose: () => void }) {
  const api = useAdminApi()
  return (
    <Modal
      title={`${template.name}: layout guide`}
      onClose={onClose}
      size="large"
      testId="layout-preview"
      footer={<GuideLink template={template} />}
    >
      <div className={styles.largeImageBox}>
        <img
          src={api.templateGuideUrl(template.key)}
          alt={`${template.name} layout guide`}
          className={styles.largeImage}
        />
      </div>
    </Modal>
  )
}

/* ---------- frames ---------- */

interface FrameRowProps {
  frame: Frame
  label: string
  onPreview: () => void
  onDetails: () => void
  onRename: () => void
  onReplace: (file: File) => void
  onDelete: () => void
}

function FrameRow({ frame, label, onPreview, onDetails, onRename, onReplace, onDelete }: FrameRowProps) {
  const api = useAdminApi()
  const replaceInput = useRef<HTMLInputElement>(null)
  const usedBy = frame.used_by ?? []
  return (
    <li className={styles.frameRow} data-testid="frame-row">
      <div className={styles.thumbBox}>
        <RetryingImage
          compact
          src={api.framePreviewUrl(frame.id, 1, frame.sha256)}
          alt={`${frame.name} sample output`}
          className={styles.thumb}
        />
        {/* The thumbnail opens the large preview too; the Preview button is its keyboard route. */}
        <button
          type="button"
          className={styles.thumbHit}
          tabIndex={-1}
          aria-hidden="true"
          onClick={onPreview}
        />
      </div>
      <div className={styles.frameText}>
        <h3 className={styles.frameName}>{frame.name}</h3>
        <span className={styles.frameMeta}>
          {label} · {frame.width} × {frame.height} px
        </span>
        <span className={styles.usage} data-testid="frame-usage">
          {usedBy.length > 0 ? `Offered by: ${usedBy.join(', ')}` : 'Not offered by any Event Profile yet'}
        </span>
        {frame.warnings.map((warning) => (
          <span key={warning} className={styles.warning}>
            {warning}
          </span>
        ))}
      </div>
      <span className={frame.builtin ? styles.builtinBadge : styles.uploadedBadge}>
        {frame.builtin ? 'Built-in' : 'Uploaded'}
      </span>
      <span className={styles.rowActions}>
        <IconButton icon="details" label={`Details of ${frame.name}`} onClick={onDetails} />
        <IconButton icon="preview" label={`Preview ${frame.name}`} onClick={onPreview} />
        {frame.builtin ? (
          <span className={styles.readOnly} title="Built-in frames can not be replaced, renamed or deleted.">
            Read-only
          </span>
        ) : (
          <>
            <IconButton icon="rename" label={`Rename ${frame.name}`} onClick={onRename} />
            <IconButton
              icon="replace"
              label={`Replace file for ${frame.name}`}
              onClick={() => replaceInput.current?.click()}
            />
            <input
              ref={replaceInput}
              type="file"
              accept="image/png"
              aria-label={`New PNG file for ${frame.name}`}
              className={styles.visuallyHidden}
              tabIndex={-1}
              onChange={(e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (file) onReplace(file)
              }}
            />
            <IconButton icon="delete" danger label={`Delete ${frame.name}`} onClick={onDelete} />
          </>
        )}
      </span>
    </li>
  )
}

function FramePreviewDialog({ frame, label, onClose }: { frame: Frame; label: string; onClose: () => void }) {
  const api = useAdminApi()
  return (
    <Modal title={frame.name} onClose={onClose} size="large" testId="frame-preview">
      <div className={styles.largeImageBox}>
        <RetryingImage
          src={api.framePreviewUrl(frame.id, 1, frame.sha256)}
          alt={`${frame.name} sample output, large`}
          className={styles.largeImage}
        />
      </div>
      <p className={styles.dialogCaption}>
        {label} · {frame.width} × {frame.height} px · sample output with placeholder photos
      </p>
    </Modal>
  )
}

function FrameDetailsDialog({ frame, label, onClose }: { frame: Frame; label: string; onClose: () => void }) {
  const usedBy = frame.used_by ?? []
  return (
    <Modal title={`${frame.name}: details`} onClose={onClose} testId="frame-details">
      <dl className={styles.specList}>
        <dt>Type</dt>
        <dd>{frame.builtin ? 'Built-in (read-only)' : 'Uploaded'}</dd>
        <dt>Layout</dt>
        <dd>{label}</dd>
        <dt>Canvas</dt>
        <dd>
          {frame.width} × {frame.height} px
        </dd>
        <dt>File size</dt>
        <dd>{kilobytes(frame.bytes)}</dd>
        <dt>Photo areas</dt>
        <dd>
          {frame.slot_transparency
            .map((share, index) => `Photo ${index + 1}: ${Math.round(share * 100)}% transparent`)
            .join(', ')}
        </dd>
        <dt>Offered by (its size)</dt>
        <dd>{usedBy.length > 0 ? usedBy.join(', ') : 'No Event Profile yet'}</dd>
      </dl>
      {frame.warnings.length > 0 && (
        <ul className={styles.requirements}>
          {frame.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      {usedBy.length > 0 && !frame.builtin && (
        <p className={styles.dialogCaption}>
          These profiles offer every frame of this size, so this frame is shown to their participants.
        </p>
      )}
    </Modal>
  )
}

function UploadDialog({
  templates,
  initialLayout,
  onClose,
  onUploaded,
}: {
  templates: TemplateSummary[]
  initialLayout: string
  onClose: () => void
  onUploaded: (name: string) => void
}) {
  const uploadMutation = useUploadFrame()
  const [layout, setLayout] = useState(initialLayout)
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const template = templates.find((t) => t.key === layout) ?? templates[0]

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0] ?? null
    setErrors([])
    const problem = picked ? fileProblem(picked) : null
    if (problem) {
      setErrors([problem])
      setFile(null)
      e.target.value = ''
      return
    }
    setFile(picked)
  }

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (uploadMutation.isPending || !template) return
    const trimmed = name.trim()
    const problems: string[] = []
    if (!trimmed) problems.push('Enter a frame name.')
    if (!file) problems.push('Choose the frame PNG file.')
    else {
      const problem = fileProblem(file)
      if (problem) problems.push(problem)
    }
    setErrors(problems)
    if (problems.length > 0 || !file) return
    try {
      await uploadMutation.mutateAsync({ templateKey: template.key, name: trimmed, file })
      onUploaded(trimmed)
    } catch (err: unknown) {
      setErrors(errorLines(err, 'Upload failed.'))
    }
  }

  return (
    <Modal title="Add frame" onClose={onClose} testId="upload-dialog" dismissible={!uploadMutation.isPending}>
      <form className={styles.uploadForm} onSubmit={(e) => void submit(e)} noValidate>
        <label className={styles.field}>
          <span className={styles.label}>Layout</span>
          <select
            value={layout}
            onChange={(e) => {
              setLayout(e.target.value)
              setErrors([])
            }}
            className={styles.input}
            disabled={uploadMutation.isPending}
          >
            {templates.map((t) => (
              <option key={t.key} value={t.key}>
                {t.name} ({t.width_px} × {t.height_px} px)
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Frame name</span>
          <input
            type="text"
            maxLength={80}
            placeholder="e.g. Gold border"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={styles.input}
            disabled={uploadMutation.isPending}
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Frame PNG file</span>
          <input
            type="file"
            accept="image/png"
            onChange={onFile}
            className={styles.fileInput}
            disabled={uploadMutation.isPending}
          />
        </label>
        {template && (
          <p className={styles.guidance} data-testid="upload-guidance">
            PNG with transparency (RGBA), exactly {template.width_px} × {template.height_px} px, not
            animated, up to 10 MB. Each photo area must be at least 95% transparent. The layout's
            Details show the exact photo positions.
          </p>
        )}
        {errors.length > 0 && (
          <div role="alert" className={styles.formAlert}>
            {errors.map((msg) => (
              <p key={msg}>{msg}</p>
            ))}
          </div>
        )}
        <div className={styles.formButtons}>
          <PillButton type="submit" tone="primary" disabled={uploadMutation.isPending}>
            {uploadMutation.isPending ? 'Uploading…' : 'Upload frame'}
          </PillButton>
          <PillButton onClick={onClose} disabled={uploadMutation.isPending}>
            Cancel
          </PillButton>
        </div>
      </form>
    </Modal>
  )
}

function RenameDialog({ frame, onClose }: { frame: Frame; onClose: () => void }) {
  const renameMutation = useRenameFrame()
  const [value, setValue] = useState(frame.name)
  const [errors, setErrors] = useState<string[]>([])
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) {
      setErrors(['Enter a frame name.'])
      return
    }
    try {
      await renameMutation.mutateAsync({ id: frame.id, name: trimmed })
      onClose()
    } catch (err: unknown) {
      setErrors(errorLines(err, 'Rename failed.'))
    }
  }
  return (
    <Modal title={`Rename ${frame.name}`} onClose={onClose} size="small" dismissible={!renameMutation.isPending}>
      <form className={styles.uploadForm} onSubmit={(e) => void submit(e)} noValidate>
        <label className={styles.field}>
          <span className={styles.label}>Frame name</span>
          <input
            type="text"
            maxLength={80}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className={styles.input}
            disabled={renameMutation.isPending}
            data-autofocus=""
          />
        </label>
        {errors.length > 0 && (
          <div role="alert" className={styles.formAlert}>
            {errors.map((msg) => (
              <p key={msg}>{msg}</p>
            ))}
          </div>
        )}
        <div className={styles.formButtons}>
          <PillButton type="submit" tone="primary" disabled={renameMutation.isPending}>
            Save name
          </PillButton>
          <PillButton onClick={onClose} disabled={renameMutation.isPending}>
            Cancel
          </PillButton>
        </div>
      </form>
    </Modal>
  )
}

/* ---------- page ---------- */

const FILTER_ALL = 'all'

export function FrameManagerPage() {
  const { data: templates, isLoading: templatesLoading, error: templatesError } = useTemplates()
  const framesQuery = useFrames()
  const replaceMutation = useReplaceFrameFile()
  const deleteMutation = useDeleteFrame()
  const [filter, setFilter] = useState(FILTER_ALL)
  const [query, setQuery] = useState('')
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [message, setMessage] = useState<Message | null>(null)
  const allFrames = framesQuery.data
  // A failed or unfinished frame list must never look like an empty library (P5-005).
  const framesState: FramesState = allFrames ? 'ready' : framesQuery.isError ? 'error' : 'loading'

  const labelOf = (key: string) => {
    const template = templates?.find((t) => t.key === key)
    return template ? layoutLabel(template) : key
  }
  const order = (key: string) => templates?.findIndex((t) => t.key === key) ?? 0
  const needle = query.trim().toLocaleLowerCase()
  const shown = (allFrames ?? [])
    .filter((f) => {
      if (filter === 'builtin' && !f.builtin) return false
      if (filter === 'uploaded' && f.builtin) return false
      if (![FILTER_ALL, 'builtin', 'uploaded'].includes(filter) && f.template_key !== filter) return false
      return f.name.toLocaleLowerCase().includes(needle)
    })
    .sort((a, b) => order(a.template_key) - order(b.template_key) || Number(b.builtin) - Number(a.builtin))

  const replace = async (frame: Frame, file: File) => {
    const problem = fileProblem(file)
    if (problem) {
      setMessage({ kind: 'error', title: 'The file was not replaced', lines: [problem] })
      return
    }
    try {
      await replaceMutation.mutateAsync({ id: frame.id, file })
      setMessage({ kind: 'success', title: 'File replaced', lines: [`${frame.name} now uses the new file.`] })
    } catch (err: unknown) {
      setMessage({ kind: 'error', title: 'The file was not replaced', lines: errorLines(err, 'Replace failed.') })
    }
  }

  const confirmDelete = async (frame: Frame) => {
    try {
      await deleteMutation.mutateAsync(frame.id)
      setDialog(null)
    } catch (err: unknown) {
      setDialog(null)
      setMessage({
        kind: 'error',
        title: `${frame.name} was not deleted`,
        lines: errorLines(err, 'Delete failed.'),
      })
    }
  }

  const filters = templates
    ? [
        { value: FILTER_ALL, label: 'All' },
        ...templates.map((t) => ({ value: t.key, label: layoutLabel(t) })),
        { value: 'builtin', label: 'Built-in' },
        { value: 'uploaded', label: 'Uploaded' },
      ]
    : []
  const uploadLayout =
    templates?.some((t) => t.key === filter) ? filter : (templates?.[0]?.key ?? '')

  return (
    <div className={styles.container}>
      <header className={styles.headerRow}>
        <h1 className={styles.heading}>Frames</h1>
        <div className={styles.headerActions}>
          {templates && templates.length > 0 && (
            <PillButton tone="primary" icon="plus" onClick={() => setDialog({ type: 'upload' })}>
              Add frame
            </PillButton>
          )}
          <Link to="/admin" className={styles.backLink}>
            Event Profiles
          </Link>
        </div>
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

      {templates && (
        <section className={styles.panel} aria-labelledby="layouts-heading">
          <h2 id="layouts-heading" className={styles.panelHeading}>
            Layouts
          </h2>
          <ul className={styles.layoutList} aria-label="Layouts">
            {templates.map((template) => (
              <LayoutRow
                key={template.key}
                template={template}
                onDetails={() => setDialog({ type: 'layout-details', template })}
                onPreview={() => setDialog({ type: 'layout-preview', template })}
              />
            ))}
          </ul>
        </section>
      )}

      {templates && (
        <section className={styles.panel} aria-labelledby="library-heading">
          <h2 id="library-heading" className={styles.panelHeading}>
            Frame library
          </h2>
          <div className={styles.libraryTools}>
            <label className={styles.searchLabel}>
              <span>Search by frame name</span>
              <input
                type="search"
                value={query}
                placeholder="e.g. Gold"
                onChange={(e) => setQuery(e.target.value)}
                className={styles.searchInput}
              />
            </label>
            <PillGroup label="Show" options={filters} value={filter} onChange={setFilter} />
          </div>

          {framesState === 'loading' && <p className={styles.loadingText}>Loading frames…</p>}
          {framesState === 'error' && (
            <div role="alert" className={styles.alert}>
              <p className={styles.alertMessage}>The frames could not be loaded.</p>
              <PillButton
                onClick={() => {
                  void framesQuery.refetch()
                }}
                disabled={framesQuery.isFetching}
              >
                {framesQuery.isFetching ? 'Loading…' : 'Try again'}
              </PillButton>
            </div>
          )}
          {framesState === 'ready' &&
            (shown.length === 0 ? (
              <p className={styles.emptyText}>
                {needle
                  ? 'No frame matches this search.'
                  : filter === 'uploaded'
                    ? 'No frames uploaded yet. Use Add frame to upload one.'
                    : 'No frames here yet.'}
              </p>
            ) : (
              <ul className={styles.frameList} aria-label="Frame library">
                {shown.map((frame) => (
                  <FrameRow
                    key={frame.id}
                    frame={frame}
                    label={labelOf(frame.template_key)}
                    onPreview={() => setDialog({ type: 'frame-preview', frame })}
                    onDetails={() => setDialog({ type: 'frame-details', frame })}
                    onRename={() => setDialog({ type: 'rename', frame })}
                    onReplace={(file) => void replace(frame, file)}
                    onDelete={() => setDialog({ type: 'delete', frame })}
                  />
                ))}
              </ul>
            ))}
        </section>
      )}

      {dialog?.type === 'layout-details' && (
        <LayoutDetailsDialog template={dialog.template} onClose={() => setDialog(null)} />
      )}
      {dialog?.type === 'layout-preview' && (
        <LayoutPreviewDialog template={dialog.template} onClose={() => setDialog(null)} />
      )}
      {dialog?.type === 'frame-preview' && (
        <FramePreviewDialog
          frame={dialog.frame}
          label={labelOf(dialog.frame.template_key)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.type === 'frame-details' && (
        <FrameDetailsDialog
          frame={dialog.frame}
          label={labelOf(dialog.frame.template_key)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.type === 'upload' && templates && (
        <UploadDialog
          templates={templates}
          initialLayout={uploadLayout}
          onClose={() => setDialog(null)}
          onUploaded={(name) => {
            setDialog(null)
            setMessage({ kind: 'success', title: 'Frame added', lines: [`${name} was added.`] })
          }}
        />
      )}
      {dialog?.type === 'rename' && <RenameDialog frame={dialog.frame} onClose={() => setDialog(null)} />}
      {dialog?.type === 'delete' && (
        <MessageDialog
          kind="confirm"
          title={`Delete ${dialog.frame.name}?`}
          onClose={() => setDialog(null)}
          actions={
            <PillButton
              tone="danger"
              disabled={deleteMutation.isPending}
              onClick={() => void confirmDelete(dialog.frame)}
            >
              Delete frame
            </PillButton>
          }
        >
          <p>The file is removed from this booth and participants can no longer choose this frame.</p>
        </MessageDialog>
      )}
      {message && (
        <MessageDialog
          kind={message.kind}
          title={message.title}
          onClose={() => setMessage(null)}
          {...(message.kind === 'success' ? { autoCloseMs: 3000 } : {})}
        >
          {message.lines.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </MessageDialog>
      )}
    </div>
  )
}
