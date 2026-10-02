import type { SystemDetails } from '../../../shared/api/adminClient'
import { PillButton } from '../components/ui/Controls'
import { useSystemDetails } from '../api/hooks'
import { when } from '../activityText'
import styles from './SystemPage.module.css'

/**
 * System: what this booth is running and whether it is well. For the organizer before an event
 * (and for whoever installs the booth): versions, the database, the disk, the address guests'
 * phones use, and the last cleanup.
 */

function gigabytes(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

function megabytes(bytes: number): string {
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

/** Below this much free space the page warns: photos need room. */
const LOW_DISK = 2 * 1024 ** 3

function Row({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className={styles.row} data-warn={warn ? '' : undefined}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

function Details({ s }: { s: SystemDetails }) {
  const lowDisk = s.disk_free_bytes < LOW_DISK
  return (
    <>
      <section className={styles.panel} aria-label="Health">
        <h2 className={styles.panelTitle}>Health</h2>
        <dl className={styles.list}>
          <Row
            label="Database"
            value={s.database === 'ok' ? 'OK' : 'Not answering'}
            warn={s.database !== 'ok'}
          />
          <Row
            label="Free disk space"
            value={`${gigabytes(s.disk_free_bytes)} of ${gigabytes(s.disk_total_bytes)}${
              lowDisk ? ' — low, clean up or free space before the event' : ''
            }`}
            warn={lowDisk}
          />
          <Row label="Photos and files" value={megabytes(s.storage_bytes)} />
          <Row label="Live event" value={s.active_event ?? 'None — the booth shows no event'} />
          <Row label="Visits in progress" value={String(s.visits_in_progress)} />
          <Row
            label="Last cleanup"
            value={
              s.last_cleanup_at
                ? `${when(s.last_cleanup_at)}${
                    s.last_cleanup_errors.length
                      ? ` (problems: ${s.last_cleanup_errors.join(', ')})`
                      : ''
                  }`
                : 'Not yet'
            }
            warn={s.last_cleanup_errors.length > 0}
          />
        </dl>
      </section>
      <section className={styles.panel} aria-label="Addresses">
        <h2 className={styles.panelTitle}>Addresses</h2>
        <dl className={styles.list}>
          <Row label="Booth screen (this machine)" value={`${s.kiosk_url}/booth`} />
          <Row label="Guests' phones reach the booth at" value={s.delivery_url} />
        </dl>
        <p className={styles.note}>
          Phones must be on the same Wi-Fi as the booth to open the take-home link.
        </p>
      </section>
      <section className={styles.panel} aria-label="Version">
        <h2 className={styles.panelTitle}>Version</h2>
        <dl className={styles.list}>
          <Row label="Instance" value={`${s.instance} (${s.profile})`} />
          <Row label="App" value={`${s.app_version} (API ${s.api_version})`} />
          <Row label="Code" value={s.git_commit ? s.git_commit.slice(0, 12) : 'unknown'} />
          <Row label="Database schema" value={s.schema_revision ?? 'unknown'} />
          <Row label="Running since" value={when(s.started_at)} />
        </dl>
      </section>
    </>
  )
}

export function SystemPage() {
  const details = useSystemDetails()
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.heading}>System</h1>
        <PillButton onClick={() => void details.refetch()} disabled={details.isFetching}>
          Check again
        </PillButton>
      </div>
      {details.isPending && <p className={styles.note}>Checking…</p>}
      {details.isError && (
        <p role="alert" className={styles.error}>
          The booth's server did not answer. Is it running?
        </p>
      )}
      {details.data && <Details s={details.data} />}
    </div>
  )
}
