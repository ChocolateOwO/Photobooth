import { useState } from 'react'

import type {
  Housekeeping,
  RetentionPolicy,
  RetentionPolicyBody,
  RetentionReport,
  RetentionRun,
} from '../../../shared/api/adminClient'
import { AdminApiError } from '../../../shared/api/adminClient'
import { Modal } from '../components/ui/Modal'
import { PillButton } from '../components/ui/Controls'
import {
  useDeleteRetentionPolicy,
  useHousekeeping,
  useMakeDefaultRetentionPolicy,
  useRetentionPolicies,
  useRetentionRuns,
  useRunRetention,
  useSaveHousekeeping,
  useSaveRetentionPolicy,
} from '../api/hooks'
import { when } from '../activityText'
import { policySummary } from '../retentionText'
import styles from './RetentionPage.module.css'

/**
 * Retention: how long this booth keeps what guests leave behind, and cleaning it up.
 *
 * Each event profile chooses one of the named policies below, and every visit keeps the values
 * of its event's policy from the moment it starts (P11-9). The booth's own files (backups,
 * logs, temporary files) follow the housekeeping settings.
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

type PolicyDays = 'originals_days' | 'outputs_days' | 'link_days' | 'metadata_days'

const POLICY_FIELDS: { key: PolicyDays; label: string; help: string }[] = [
  {
    key: 'originals_days',
    label: 'Original photos',
    help: 'The photos as the camera took them, after the visit ends.',
  },
  {
    key: 'outputs_days',
    label: 'Finished photos',
    help: 'The prints and strips; the take-home link stops with them.',
  },
  {
    key: 'link_days',
    label: 'Take-home link works for',
    help: 'Never longer than the finished photos.',
  },
  {
    key: 'metadata_days',
    label: 'Visit records',
    help: 'When visits are made anonymous or deleted (see below).',
  },
]

type HousekeepingDays = 'activity_log_days' | 'backup_days' | 'app_log_days' | 'temp_hours'

const HOUSEKEEPING_FIELDS: { key: HousekeepingDays; label: string; unit: string }[] = [
  { key: 'activity_log_days', label: 'Activity log', unit: 'days' },
  { key: 'backup_days', label: 'Database backups', unit: 'days' },
  { key: 'app_log_days', label: 'Application logs', unit: 'days' },
  { key: 'temp_hours', label: 'Unfinished temporary files', unit: 'hours' },
]

function problemOf(error: unknown): string | null {
  if (error instanceof AdminApiError) return error.messages.join(' ')
  return error ? 'The booth did not answer. Try again.' : null
}

const NEW_POLICY: RetentionPolicyBody = {
  name: '',
  originals_days: 7,
  outputs_days: 30,
  link_days: 7,
  metadata_mode: 'keep',
  metadata_days: 90,
  revision: 1,
}

/** Adds a policy (`policy` null) or changes one. Visits already made keep their deadlines. */
function PolicyEditor({ policy, onDone }: { policy: RetentionPolicy | null; onDone: () => void }) {
  const save = useSaveRetentionPolicy()
  const [draft, setDraft] = useState<RetentionPolicyBody>(policy ?? NEW_POLICY)
  const problem = problemOf(save.error)
  return (
    <form
      className={styles.panel}
      aria-label={policy ? `Edit ${policy.name}` : 'New retention policy'}
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate({ id: policy?.id ?? null, policy: draft }, { onSuccess: onDone })
      }}
    >
      <h3 className={styles.panelTitle}>{policy ? `Edit ${policy.name}` : 'New policy'}</h3>
      <div className={styles.fields}>
        <label className={styles.field}>
          <span className={styles.label}>Name</span>
          <input
            className={styles.name}
            value={draft.name}
            maxLength={60}
            required
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          />
        </label>
        {POLICY_FIELDS.map((field) => (
          <label key={field.key} className={styles.field}>
            <span className={styles.label}>{field.label}</span>
            <span className={styles.inputRow}>
              <input
                type="number"
                min={1}
                max={3650}
                value={draft[field.key]}
                onChange={(event) => setDraft({ ...draft, [field.key]: Number(event.target.value) })}
              />
              <span className={styles.muted}>days</span>
            </span>
            <span className={styles.help}>{field.help}</span>
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
      {policy && policy.used_by > 0 && (
        <p className={styles.help}>
          Changes apply to visits that start from now on. Visits already made keep the deadlines
          they started with.
        </p>
      )}
      {problem && (
        <p role="alert" className={styles.error}>
          {problem}
        </p>
      )}
      <div className={styles.actions}>
        <PillButton type="submit" tone="primary" disabled={save.isPending || !draft.name.trim()}>
          {policy ? 'Save policy' : 'Add policy'}
        </PillButton>
        <PillButton type="button" onClick={onDone}>
          Cancel
        </PillButton>
      </div>
    </form>
  )
}

function Policies({ policies }: { policies: RetentionPolicy[] }) {
  // The policy being edited: an id, 'new', or none.
  const [editing, setEditing] = useState<string | null>(null)
  const remove = useDeleteRetentionPolicy()
  const makeDefault = useMakeDefaultRetentionPolicy()
  const problem = problemOf(remove.error) ?? problemOf(makeDefault.error)
  const edited = policies.find((policy) => policy.id === editing) ?? null
  return (
    <section className={styles.panel} aria-label="Retention policies">
      <h2 className={styles.panelTitle}>Retention policies</h2>
      <p className={styles.muted}>
        Each event profile chooses one of these (Event Profiles → Edit → Retention policy). New
        profiles start with the default. A visit keeps the policy it started with.
      </p>
      <ul className={styles.policies} data-testid="retention-policies">
        {policies.map((policy) => (
          <li key={policy.id} className={styles.policy} data-testid="retention-policy">
            <div className={styles.policyText}>
              <span className={styles.policyName}>
                {policy.name}
                {policy.is_default && <span className={styles.badge}>Default</span>}
              </span>
              <span className={styles.muted}>{policySummary(policy)}</span>
              <span className={styles.muted}>
                Used by {policy.used_by} event profile{policy.used_by === 1 ? '' : 's'}
              </span>
            </div>
            <div className={styles.actions}>
              <PillButton onClick={() => setEditing(policy.id)} aria-label={`Edit ${policy.name}`}>
                Edit
              </PillButton>
              {!policy.is_default && (
                <PillButton
                  onClick={() => makeDefault.mutate(policy.id)}
                  disabled={makeDefault.isPending}
                  aria-label={`Make ${policy.name} the default`}
                >
                  Make default
                </PillButton>
              )}
              {!policy.is_default && policy.used_by === 0 && (
                <PillButton
                  tone="danger"
                  onClick={() => remove.mutate(policy.id)}
                  disabled={remove.isPending}
                  aria-label={`Delete ${policy.name}`}
                >
                  Delete
                </PillButton>
              )}
            </div>
          </li>
        ))}
      </ul>
      {problem && (
        <p role="alert" className={styles.error}>
          {problem}
        </p>
      )}
      {editing === null && (
        <div className={styles.actions}>
          <PillButton onClick={() => setEditing('new')}>Add policy</PillButton>
        </div>
      )}
      {editing !== null && (
        <PolicyEditor
          key={editing === 'new' ? 'new' : `${editing}-${edited?.revision ?? 0}`}
          policy={editing === 'new' ? null : edited}
          onDone={() => setEditing(null)}
        />
      )}
    </section>
  )
}

function HousekeepingForm({ settings }: { settings: Housekeeping }) {
  const save = useSaveHousekeeping()
  // A new revision remounts the form (see the key below), so the draft starts from it.
  const [draft, setDraft] = useState(settings)
  const changed = JSON.stringify(draft) !== JSON.stringify(settings)
  const problem = problemOf(save.error)
  return (
    <form
      className={styles.panel}
      aria-label="Booth housekeeping"
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate(draft)
      }}
    >
      <h2 className={styles.panelTitle}>Booth housekeeping</h2>
      <p className={styles.muted}>What belongs to the whole booth rather than to one event.</p>
      <div className={styles.fields}>
        {HOUSEKEEPING_FIELDS.map((field) => (
          <label key={field.key} className={styles.field}>
            <span className={styles.label}>{field.label}</span>
            <span className={styles.inputRow}>
              <input
                type="number"
                min={1}
                max={field.unit === 'hours' ? 720 : 3650}
                value={draft[field.key]}
                onChange={(event) => setDraft({ ...draft, [field.key]: Number(event.target.value) })}
              />
              <span className={styles.muted}>{field.unit}</span>
            </span>
          </label>
        ))}
      </div>
      {problem && (
        <p role="alert" className={styles.error}>
          {problem}
        </p>
      )}
      {save.isSuccess && !changed && <p className={styles.ok}>Saved.</p>}
      <div className={styles.actions}>
        <PillButton type="submit" tone="primary" disabled={!changed || save.isPending}>
          Save housekeeping
        </PillButton>
        <PillButton type="button" disabled={!changed} onClick={() => setDraft(settings)}>
          Undo changes
        </PillButton>
      </div>
    </form>
  )
}
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

function Cleanup() {
  const run = useRunRetention()
  const [preview, setPreview] = useState<RetentionReport | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [understood, setUnderstood] = useState(false)
  const [done, setDone] = useState<RetentionReport | null>(null)

  const failure =
    run.error instanceof AdminApiError
      ? run.error.status === 409
        ? 'The housekeeping settings changed since the check. Check again before deleting.'
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
                    // Only under the settings the check showed: changed ones are refused.
                    { dryRun: false, housekeepingRevision: preview.housekeeping_revision },
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
  const policies = useRetentionPolicies()
  const housekeeping = useHousekeeping()
  const runs = useRetentionRuns()
  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>Retention</h1>
      <p className={styles.intro}>
        Guests&apos; photos and visit records are deleted for good once their time is up. Visits
        still going are never touched, and only this booth&apos;s own folders are ever cleaned.
      </p>
      {(policies.isError || housekeeping.isError) && (
        <p role="alert" className={styles.error}>
          The retention settings could not be loaded.
        </p>
      )}
      {policies.data && <Policies policies={policies.data} />}
      {housekeeping.data && (
        <HousekeepingForm
          key={`housekeeping-${housekeeping.data.revision}`}
          settings={housekeeping.data}
        />
      )}
      {/* New settings start a new check: an earlier one may no longer be true (P11-008). */}
      {housekeeping.data && <Cleanup key={`cleanup-${housekeeping.data.revision}`} />}
      <Runs runs={runs.data ?? []} />
    </div>
  )
}
