import { useState } from 'react'

import type {
  RetentionPolicy,
  RetentionReport,
  RetentionRun,
} from '../../../shared/api/adminClient'
import { AdminApiError } from '../../../shared/api/adminClient'
import { Modal } from '../components/ui/Modal'
import { PillButton } from '../components/ui/Controls'
import {
  useRetentionPolicy,
  useRetentionRuns,
  useRunRetention,
  useSaveRetentionPolicy,
} from '../api/hooks'
import { when } from '../activityText'
import styles from './RetentionPage.module.css'

/**
 * Retention: how long this booth keeps what guests leave behind, and cleaning it up.
 *
 * The booth cleans up by itself every hour and before it opens; organizers can also look first
 * (what would go, nothing is deleted) and then delete now. Deleting can not be undone, so it
 * always asks, with the counts in front of you, and only a ticked box lets it go ahead.
 */

const CATEGORY_NAMES: Record<string, string> = {
  originals: 'Original photos',
  outputs: 'Finished photos (their links stop working)',
  visits_anonymized: 'Visits made anonymous',
  visits_deleted: 'Visits deleted completely',
  activity: 'Activity log records',
  temp: 'Unfinished temporary files',
  backups: 'Database backups (the newest is always kept)',
  app_logs: 'Old application logs',
}

const TRIGGERS: Record<string, string> = {
  manual: 'By hand',
  schedule: 'Every hour',
  startup: 'When the booth started',
}

function size(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
  return bytes ? `${bytes} B` : ''
}

function total(report: Pick<RetentionReport, 'counts'>): number {
  return report.counts.reduce((sum, row) => sum + row.items, 0)
}

type NumberField = Exclude<keyof RetentionPolicy, 'metadata_mode' | 'revision' | 'updated_at'>

const FIELDS: { key: NumberField; label: string; unit: string; help: string }[] = [
  {
    key: 'originals_days',
    label: 'Original photos',
    unit: 'days',
    help: 'The photos as the camera took them, after the visit ends.',
  },
  {
    key: 'outputs_days',
    label: 'Finished photos',
    unit: 'days',
    help: 'The prints and strips; the take-home link stops with them.',
  },
  {
    key: 'link_days',
    label: 'Take-home link works for',
    unit: 'days',
    help: 'For links made from now on. Never longer than the finished photos.',
  },
  {
    key: 'metadata_days',
    label: 'Visit records',
    unit: 'days',
    help: 'When visits are made anonymous or deleted (see below).',
  },
  { key: 'activity_log_days', label: 'Activity log', unit: 'days', help: '' },
  { key: 'backup_days', label: 'Database backups', unit: 'days', help: '' },
  { key: 'app_log_days', label: 'Application logs', unit: 'days', help: '' },
  { key: 'temp_hours', label: 'Unfinished temporary files', unit: 'hours', help: '' },
]

function ReportTable({ report }: { report: Pick<RetentionReport, 'counts'> }) {
  return (
    <table className={styles.table} data-testid="retention-counts">
      <tbody>
        {report.counts.map((row) => (
          <tr key={row.category}>
            <th scope="row">{CATEGORY_NAMES[row.category] ?? row.category}</th>
            <td>{row.items}</td>
            <td className={styles.muted}>{size(row.bytes)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function PolicyForm({ policy }: { policy: RetentionPolicy }) {
  const save = useSaveRetentionPolicy()
  // A new revision remounts the form (see the key below), so the draft starts from it.
  const [draft, setDraft] = useState(policy)
  const changed = JSON.stringify(draft) !== JSON.stringify(policy)
  const problem =
    save.error instanceof AdminApiError ? save.error.messages.join(' ') : save.error ? 'Not saved.' : null

  return (
    <form
      className={styles.panel}
      aria-label="Retention policy"
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate(draft)
      }}
    >
      <h2 className={styles.panelTitle}>How long the booth keeps things</h2>
      <div className={styles.fields}>
        {FIELDS.map((field) => (
          <label key={field.key} className={styles.field}>
            <span className={styles.label}>{field.label}</span>
            <span className={styles.inputRow}>
              <input
                type="number"
                min={1}
                max={field.unit === 'hours' ? 720 : 3650}
                value={draft[field.key]}
                onChange={(event) =>
                  setDraft({ ...draft, [field.key]: Number(event.target.value) })
                }
              />
              <span className={styles.muted}>{field.unit}</span>
            </span>
            {field.help && <span className={styles.help}>{field.help}</span>}
          </label>
        ))}
        <label className={styles.field}>
          <span className={styles.label}>After that, visit records are</span>
          <select
            value={draft.metadata_mode}
            onChange={(event) =>
              setDraft({
                ...draft,
                metadata_mode: event.target.value as RetentionPolicy['metadata_mode'],
              })
            }
          >
            <option value="keep">Kept (counts and times only, no photos)</option>
            <option value="anonymize">Made anonymous</option>
            <option value="delete">Deleted completely</option>
          </select>
        </label>
      </div>
      {problem && (
        <p role="alert" className={styles.error}>
          {problem}
        </p>
      )}
      {save.isSuccess && !changed && <p className={styles.ok}>Saved.</p>}
      <div className={styles.actions}>
        <PillButton type="submit" tone="primary" disabled={!changed || save.isPending}>
          Save policy
        </PillButton>
        <PillButton type="button" disabled={!changed} onClick={() => setDraft(policy)}>
          Undo changes
        </PillButton>
      </div>
    </form>
  )
}

function Cleanup() {
  const run = useRunRetention()
  const [preview, setPreview] = useState<RetentionReport | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [understood, setUnderstood] = useState(false)
  const [done, setDone] = useState<RetentionReport | null>(null)

  const failure =
    run.error instanceof AdminApiError
      ? run.error.status === 409
        ? 'The policy changed since the check. Check again before deleting.'
        : run.error.messages.join(' ')
      : run.error
        ? 'The booth did not answer. Try again.'
        : null

  const look = () => {
    setDone(null)
    run.mutate(
      { dryRun: true },
      {
        onSuccess: (report) => setPreview(report),
      },
    )
  }

  return (
    <section className={styles.panel} aria-label="Clean up now">
      <h2 className={styles.panelTitle}>Clean up now</h2>
      <p className={styles.muted}>
        The booth cleans up by itself every hour and whenever it starts. Look first to see what
        would go; nothing is deleted until you confirm.
      </p>
      <div className={styles.actions}>
        <PillButton onClick={look} disabled={run.isPending}>
          Check what would be deleted
        </PillButton>
      </div>
      {failure && (
        <p role="alert" className={styles.error}>
          {failure}
        </p>
      )}
      {preview && (
        <>
          <ReportTable report={preview} />
          {!preview.complete ? (
            // An incomplete check is not a basis for deleting anything (P11-009).
            <p role="alert" className={styles.error}>
              Some things could not be checked: {preview.errors.join(', ')}. Check again before
              deleting.
            </p>
          ) : total(preview) === 0 ? (
            <p className={styles.ok}>Nothing is past its time.</p>
          ) : (
            <div className={styles.actions}>
              <PillButton tone="danger" onClick={() => setConfirming(true)}>
                Delete these now
              </PillButton>
            </div>
          )}
        </>
      )}
      {done && (
        <p className={done.complete ? styles.ok : styles.error} role="status">
          Deleted {total(done)} item{total(done) === 1 ? '' : 's'}.
          {done.errors.length
            ? ` Some could not be deleted and will be tried again: ${done.errors.join(', ')}.`
            : ''}
        </p>
      )}
      {confirming && preview && (
        <Modal
          title="Delete permanently?"
          tone="warning"
          onClose={() => {
            setConfirming(false)
            setUnderstood(false)
          }}
          footer={
            <>
              <PillButton
                onClick={() => {
                  setConfirming(false)
                  setUnderstood(false)
                }}
              >
                Keep everything
              </PillButton>
              <PillButton
                tone="danger"
                disabled={!understood || run.isPending}
                onClick={() =>
                  run.mutate(
                    // Only under the policy the check showed: a changed policy is refused.
                    { dryRun: false, policyRevision: preview.policy_revision },
                    {
                      onSuccess: (report) => {
                        setDone(report)
                        setPreview(null)
                        setConfirming(false)
                        setUnderstood(false)
                      },
                      onError: () => {
                        // Whatever went wrong, the shown check is no longer to be trusted.
                        setPreview(null)
                        setConfirming(false)
                        setUnderstood(false)
                      },
                    },
                  )
                }
              >
                Delete permanently
              </PillButton>
            </>
          }
        >
          <ReportTable report={preview} />
          <label className={styles.confirm}>
            <input
              type="checkbox"
              checked={understood}
              onChange={(event) => setUnderstood(event.target.checked)}
            />
            I understand these are deleted for good and can not be brought back.
          </label>
        </Modal>
      )}
    </section>
  )
}

function Runs({ runs }: { runs: RetentionRun[] }) {
  return (
    <section className={styles.panel} aria-label="Recent cleanups">
      <h2 className={styles.panelTitle}>Recent cleanups</h2>
      {runs.length === 0 ? (
        <p className={styles.muted}>None yet.</p>
      ) : (
        <table className={styles.table} data-testid="retention-runs">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">How</th>
              <th scope="col">Deleted</th>
              <th scope="col">Problems</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td>{when(run.started_at)}</td>
                <td>
                  {TRIGGERS[run.trigger] ?? run.trigger}
                  {run.dry_run ? ' (check only)' : ''}
                </td>
                <td>{run.dry_run ? '—' : total(run)}</td>
                <td>{run.errors.length ? run.errors.join(', ') : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export function RetentionPage() {
  const policy = useRetentionPolicy()
  const runs = useRetentionRuns()
  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>Retention</h1>
      <p className={styles.intro}>
        Guests&apos; photos and visit records are deleted for good once their time is up. Visits
        still going are never touched, and only this booth&apos;s own folders are ever cleaned.
      </p>
      {policy.isError && (
        <p role="alert" className={styles.error}>
          The retention policy could not be loaded.
        </p>
      )}
      {policy.data && <PolicyForm key={`policy-${policy.data.revision}`} policy={policy.data} />}
      {/* A new policy starts a new check: an earlier one may no longer be true (P11-008). */}
      {policy.data && <Cleanup key={`cleanup-${policy.data.revision}`} />}
      <Runs runs={runs.data ?? []} />
    </div>
  )
}
