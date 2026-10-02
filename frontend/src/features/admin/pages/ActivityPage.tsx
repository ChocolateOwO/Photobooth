import { useState } from 'react'

import { PillButton, PillGroup } from '../components/ui/Controls'
import { useActivity } from '../api/hooks'
import { actorName, describe, when } from '../activityText'
import styles from './ActivityPage.module.css'

/**
 * The activity log: what happened at the booth, on guests' phones and in Admin, newest first.
 *
 * Each line is a small allowlisted record: never a take-home link, a password, a file path, an
 * IP address or anything typed. Organizer tests are not logged as guests' visits.
 */

const WHO = [
  { value: '', label: 'Everything' },
  { value: 'booth', label: 'Booth' },
  { value: 'guest', label: 'Guest phones' },
  { value: 'admin', label: 'Organizers' },
  { value: 'system', label: 'System' },
] as const
type Who = (typeof WHO)[number]['value']

export function ActivityPage() {
  const [who, setWho] = useState<Who>('')
  const activity = useActivity(who ? [who] : [])
  const records = activity.data?.pages.flatMap((page) => page.records) ?? []

  return (
    <div className={styles.container}>
      <h1 className={styles.heading}>Activity log</h1>
      <PillGroup
        label="Show"
        options={WHO.map((w) => ({ value: w.value, label: w.label }))}
        value={who}
        onChange={(value) => setWho(value as Who)}
      />
      {activity.isPending && <p className={styles.muted}>Loading…</p>}
      {activity.isError && (
        <p role="alert" className={styles.error}>
          The activity log could not be loaded. Try again in a moment.
        </p>
      )}
      {activity.isSuccess && records.length === 0 && (
        <p className={styles.muted}>Nothing recorded yet.</p>
      )}
      {records.length > 0 && (
        <ol className={styles.log} data-testid="activity-log">
          {records.map((record) => (
            <li key={record.id} className={styles.row} data-type={record.type}>
              <time dateTime={record.at} className={styles.time}>
                {when(record.at)}
              </time>
              <span className={styles.actor} data-actor={record.actor}>
                {actorName(record)}
              </span>
              <span className={styles.what}>{describe(record)}</span>
            </li>
          ))}
        </ol>
      )}
      {activity.hasNextPage && (
        <div className={styles.more}>
          <PillButton
            disabled={activity.isFetchingNextPage}
            onClick={() => void activity.fetchNextPage()}
          >
            {activity.isFetchingNextPage ? 'Loading…' : 'Show older'}
          </PillButton>
        </div>
      )}
    </div>
  )
}
