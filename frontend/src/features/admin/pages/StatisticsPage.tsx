import { useMemo, useState } from 'react'

import type { Statistics } from '../../../shared/api/adminClient'
import { PillGroup } from '../components/ui/Controls'
import { useProfiles, useStatistics } from '../api/hooks'
import { filterName, layoutName } from '../activityText'
import { periodRange, PERIODS, type Period } from '../period'
import styles from './StatisticsPage.module.css'

/**
 * Statistics: how the event is going, in a few numbers and three simple charts.
 *
 * Counted from the visits themselves (organizer tests never count). Every chart also has its
 * numbers written next to its bars, so nothing depends on colour or hovering.
 */

function Tile({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div className={styles.tile}>
      <p className={styles.tileLabel}>{label}</p>
      <p className={styles.tileValue}>{value}</p>
      {note && <p className={styles.tileNote}>{note}</p>}
    </div>
  )
}

function percent(part: number, whole: number): string {
  return whole ? `${Math.round((part / whole) * 100)}%` : '—'
}

/** Horizontal bars, one per row, each labelled with its name and its count. */
function BarList({
  title,
  rows,
  empty,
}: {
  title: string
  rows: { key: string; label: string; count: number }[]
  empty: string
}) {
  const top = Math.max(1, ...rows.map((row) => row.count))
  return (
    <section className={styles.panel} aria-label={title}>
      <h2 className={styles.panelTitle}>{title}</h2>
      {rows.length === 0 ? (
        <p className={styles.empty}>{empty}</p>
      ) : (
        <ul className={styles.barList}>
          {rows.map((row) => (
            <li key={row.key} className={styles.barRow} title={`${row.label}: ${row.count}`}>
              <span className={styles.barLabel}>{row.label}</span>
              <span className={styles.barTrack} aria-hidden="true">
                <span className={styles.bar} style={{ width: `${(row.count / top) * 100}%` }} />
              </span>
              <span className={styles.barValue}>{row.count}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Visits started per hour of the booth's day: 24 columns, the busy hours stand out. */
function Hours({ stats }: { stats: Statistics }) {
  const counts = new Map(stats.by_hour.map((row) => [Number(row.key), row.count]))
  const top = Math.max(1, ...counts.values())
  const hours = Array.from({ length: 24 }, (_, hour) => ({ hour, count: counts.get(hour) ?? 0 }))
  return (
    <section className={styles.panel} aria-label="Visits by hour">
      <h2 className={styles.panelTitle}>Visits by hour</h2>
      {stats.visits === 0 ? (
        <p className={styles.empty}>No visits in this period.</p>
      ) : (
        <>
          <div className={styles.hours} role="img" aria-label="Visits started in each hour">
            {hours.map(({ hour, count }) => (
              <div
                key={hour}
                className={styles.hourColumn}
                title={`${String(hour).padStart(2, '0')}:00–${String(hour).padStart(2, '0')}:59: ${count} visit${count === 1 ? '' : 's'}`}
              >
                <span className={styles.hourCount}>{count || ''}</span>
                <span
                  className={styles.hourBar}
                  style={{ height: `${(count / top) * 100}%` }}
                  data-empty={count === 0 ? '' : undefined}
                />
                <span className={styles.hourLabel}>{hour % 3 === 0 ? hour : ''}</span>
              </div>
            ))}
          </div>
          <table className={styles.visuallyHidden}>
            <caption>Visits started in each hour</caption>
            <thead>
              <tr>
                <th scope="col">Hour</th>
                <th scope="col">Visits</th>
              </tr>
            </thead>
            <tbody>
              {hours
                .filter((row) => row.count > 0)
                .map(({ hour, count }) => (
                  <tr key={hour}>
                    <td>{String(hour).padStart(2, '0')}:00</td>
                    <td>{count}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}

export function StatisticsPage() {
  const [period, setPeriod] = useState<Period>('today')
  const [profileId, setProfileId] = useState<string>('')
  const profiles = useProfiles(true)
  // Fixed once per choice, so the page does not ask again on every render.
  const range = useMemo(() => periodRange(period), [period])
  const stats = useStatistics({ ...range, ...(profileId ? { profileId } : {}) })
  const s = stats.data

  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        <h1 className={styles.heading}>Statistics</h1>
      </div>
      <div className={styles.filters}>
        <PillGroup
          label="Period"
          options={PERIODS.map((p) => ({ value: p.value, label: p.label }))}
          value={period}
          onChange={(value) => setPeriod(value as Period)}
        />
        <label className={styles.field}>
          <span>Event</span>
          <select value={profileId} onChange={(event) => setProfileId(event.target.value)}>
            <option value="">All events</option>
            {(profiles.data ?? []).map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.settings.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {stats.isPending && <p className={styles.empty}>Counting…</p>}
      {stats.isError && (
        <p role="alert" className={styles.error}>
          The statistics could not be loaded. Try again in a moment.
        </p>
      )}
      {s && (
        <>
          <div className={styles.tiles} data-testid="statistics-tiles">
            <Tile label="Visits" value={s.visits} />
            <Tile
              label="Photos made"
              value={s.finished}
              note={`${percent(s.finished, s.visits)} of visits`}
            />
            <Tile label="Photos taken" value={s.photos} note={`${s.retakes} retake${s.retakes === 1 ? '' : 's'}`} />
            <Tile
              label="Decorated"
              value={s.decorated}
              note={`${percent(s.decorated, s.finished)} of finished visits`}
            />
            <Tile
              label="Links opened"
              value={s.links_opened}
              note={`${percent(s.links_opened, s.finished)} of finished visits`}
            />
            <Tile label="Downloads" value={s.downloads} />
            <Tile
              label="Average visit"
              value={s.average_minutes === null ? '—' : `${s.average_minutes} min`}
              note="start to finished photos"
            />
            <Tile
              label="Ended early"
              value={s.cancelled + s.abandoned + s.errors}
              note={`${s.cancelled} left · ${s.abandoned} timed out · ${s.errors} errors`}
            />
          </div>
          <div className={styles.charts}>
            <Hours stats={s} />
            <BarList
              title="Visits by layout"
              rows={s.by_layout.map((row) => ({
                key: row.key,
                label: layoutName(row.key),
                count: row.count,
              }))}
              empty="No frame chosen yet."
            />
            <BarList
              title="Filters on finished photos"
              rows={s.by_filter.map((row) => ({
                key: row.key,
                label: filterName(row.key),
                count: row.count,
              }))}
              empty="No finished photos yet."
            />
          </div>
        </>
      )}
    </div>
  )
}
