import { useMemo, useState } from 'react'

import type { Visit } from '../../../shared/api/adminClient'
import { Modal } from '../components/ui/Modal'
import { PillButton, PillGroup } from '../components/ui/Controls'
import { useHistory, useProfiles, useVisit } from '../api/hooks'
import {
  actorName,
  describe,
  duration,
  endReason,
  filterName,
  layoutName,
  stateName,
  when,
} from '../activityText'
import { periodRange, PERIODS, type Period } from '../period'
import styles from './HistoryPage.module.css'

/**
 * Session history: every guest's visit, newest first, and what happened in each one.
 *
 * Only facts are shown (times, counts, the filter, whether the link was opened); never a photo,
 * a link or anything a guest typed. Organizer tests are not guests' visits and never appear.
 */

const PAGE = 25

const STATES = [
  { value: '', label: 'Any' },
  { value: 'finished', label: 'Photos made' },
  { value: 'early', label: 'Ended early' },
  { value: 'open', label: 'In progress' },
] as const
type StateFilter = (typeof STATES)[number]['value']

const STATE_GROUPS: Record<StateFilter, string[]> = {
  '': [],
  finished: ['delivered', 'completed'],
  early: ['cancelled', 'abandoned', 'error'],
  open: ['eligibility_ok', 'capturing', 'reviewing'],
}

function decoration(visit: Visit): string {
  if (!visit.outputs) return '—'
  const parts = [
    visit.filter && visit.filter !== 'none' ? filterName(visit.filter) : null,
    visit.stickers ? `${visit.stickers} sticker${visit.stickers === 1 ? '' : 's'}` : null,
  ].filter(Boolean)
  return parts.length ? parts.join(', ') : 'none'
}

function VisitDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const detail = useVisit(id)
  const visit = detail.data?.visit
  return (
    <Modal title="Visit" onClose={onClose} size="large" testId="visit-dialog">
      {detail.isPending && <p className={styles.muted}>Loading…</p>}
      {detail.isError && (
        <p role="alert" className={styles.error}>
          This visit could not be loaded.
        </p>
      )}
      {visit && detail.data && (
        <div className={styles.detail}>
          <dl className={styles.facts}>
            <div>
              <dt>Started</dt>
              <dd>{when(visit.started_at)}</dd>
            </div>
            <div>
              <dt>Ended</dt>
              <dd>{visit.ended_at ? when(visit.ended_at) : 'Not yet'}</dd>
            </div>
            <div>
              <dt>Result</dt>
              <dd>
                {stateName(visit.state)}
                {endReason(visit.end_reason) ? ` (${endReason(visit.end_reason)})` : ''}
              </dd>
            </div>
            <div>
              <dt>Event</dt>
              <dd>{visit.profile_name ?? 'Deleted event'}</dd>
            </div>
            <div>
              <dt>Layout</dt>
              <dd>{layoutName(visit.layout)}</dd>
            </div>
            <div>
              <dt>Photos</dt>
              <dd>
                {visit.photos} taken, {visit.retakes} retaken
              </dd>
            </div>
            <div>
              <dt>Finished photos</dt>
              <dd>{visit.outputs}</dd>
            </div>
            <div>
              <dt>Decoration</dt>
              <dd>{decoration(visit)}</dd>
            </div>
            <div>
              <dt>Take-home link</dt>
              <dd>
                {!visit.link_issued
                  ? 'Not shown'
                  : visit.link_opened
                    ? `Opened, ${visit.downloads} download${visit.downloads === 1 ? '' : 's'}`
                    : 'Not opened'}
              </dd>
            </div>
          </dl>
          <h3 className={styles.timelineTitle}>What happened</h3>
          {detail.data.timeline.length === 0 ? (
            <p className={styles.muted}>Nothing was recorded for this visit.</p>
          ) : (
            <ol className={styles.timeline} data-testid="visit-timeline">
              {detail.data.timeline.map((record) => (
                <li key={record.id}>
                  <time dateTime={record.at}>{when(record.at)}</time>
                  <span>{describe(record)}</span>
                  <span className={styles.muted}>{actorName(record)}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </Modal>
  )
}

export function HistoryPage() {
  const [period, setPeriod] = useState<Period>('today')
  const [profileId, setProfileId] = useState('')
  const [state, setState] = useState<StateFilter>('')
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const profiles = useProfiles(true)
  const range = useMemo(() => periodRange(period), [period])
  const history = useHistory({
    ...range,
    ...(profileId ? { profileId } : {}),
    states: STATE_GROUPS[state],
    offset,
    limit: PAGE,
  })
  const page = history.data
  const choose = <T,>(set: (value: T) => void) => (value: T) => {
    set(value)
    setOffset(0)
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>History</h1>
      <div className={styles.filters}>
        <PillGroup
          label="Period"
          options={PERIODS.map((p) => ({ value: p.value, label: p.label }))}
          value={period}
          onChange={(value) => choose(setPeriod)(value as Period)}
        />
        <PillGroup
          label="Result"
          options={STATES.map((s) => ({ value: s.value, label: s.label }))}
          value={state}
          onChange={(value) => choose(setState)(value as StateFilter)}
        />
        <label className={styles.field}>
          <span>Event</span>
          <select
            value={profileId}
            onChange={(event) => choose(setProfileId)(event.target.value)}
          >
            <option value="">All events</option>
            {(profiles.data ?? []).map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.settings.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {history.isPending && <p className={styles.muted}>Loading…</p>}
      {history.isError && (
        <p role="alert" className={styles.error}>
          The history could not be loaded. Try again in a moment.
        </p>
      )}
      {page && page.total === 0 && <p className={styles.muted}>No visits in this period.</p>}
      {page && page.total > 0 && (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table} data-testid="history-table">
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Event</th>
                  <th scope="col">Layout</th>
                  <th scope="col">Result</th>
                  <th scope="col">Photos</th>
                  <th scope="col">Decoration</th>
                  <th scope="col">Link</th>
                  <th scope="col">Took</th>
                  <th scope="col">
                    <span className={styles.visuallyHidden}>Details</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {page.visits.map((visit) => (
                  <tr key={visit.id}>
                    <td>{when(visit.started_at)}</td>
                    <td>{visit.profile_name ?? 'Deleted event'}</td>
                    <td>{layoutName(visit.layout)}</td>
                    <td>
                      <span className={styles.state} data-state={visit.state}>
                        {stateName(visit.state)}
                      </span>
                    </td>
                    <td>
                      {visit.photos}
                      {visit.retakes ? ` (+${visit.retakes} retaken)` : ''}
                    </td>
                    <td>{decoration(visit)}</td>
                    <td>
                      {!visit.link_issued
                        ? '—'
                        : visit.link_opened
                          ? `Opened · ${visit.downloads}↓`
                          : 'Not opened'}
                    </td>
                    <td>{duration(visit) ?? '…'}</td>
                    <td>
                      <PillButton onClick={() => setOpen(visit.id)}>Details</PillButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className={styles.pager}>
            <PillButton disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Newer
            </PillButton>
            <span className={styles.muted}>
              {offset + 1}–{Math.min(offset + PAGE, page.total)} of {page.total}
            </span>
            <PillButton
              disabled={offset + PAGE >= page.total}
              onClick={() => setOffset(offset + PAGE)}
            >
              Older
            </PillButton>
          </div>
        </>
      )}
      {open && <VisitDialog id={open} onClose={() => setOpen(null)} />}
    </div>
  )
}
