/** The periods Admin offers for history and statistics, on the booth's own clock. */

export type Period = 'today' | 'yesterday' | 'week' | 'all'

export const PERIODS: readonly { value: Period; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'week', label: 'Last 7 days' },
  { value: 'all', label: 'All time' },
]

export interface Range {
  since?: string
  until?: string
}

/** Local midnight, `daysBack` days before `now`'s day (calendar days, whatever the clock does). */
function midnight(now: Date, daysBack = 0): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysBack)
}

/** The period as ISO instants; "today" starts at the booth's local midnight. */
export function periodRange(period: Period, now: Date = new Date()): Range {
  switch (period) {
    case 'today':
      return { since: midnight(now).toISOString() }
    case 'yesterday':
      return { since: midnight(now, 1).toISOString(), until: midnight(now).toISOString() }
    case 'week':
      return { since: midnight(now, 6).toISOString() }
    case 'all':
      return {}
  }
}
