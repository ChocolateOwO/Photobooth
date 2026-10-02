import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type {
  ActivityRecord,
  Statistics,
  Visit,
  VisitDetail,
} from '../../../shared/api/adminClient'
import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

/**
 * Phase 10 in Admin: History lists guests' visits and opens one with its timeline, Statistics
 * shows the counts with every chart number written out, and the Activity log pages back in time.
 */

function signedIn(): FakeAdminServer {
  const server = new FakeAdminServer()
  server.signedIn = true
  return server
}

function record(id: string, type: string, extra: Partial<ActivityRecord> = {}): ActivityRecord {
  return {
    id,
    at: '2026-10-02T03:04:05Z',
    type,
    actor: 'booth',
    session_id: 'v1',
    profile_id: 'p1',
    admin_username: null,
    payload: {},
    ...extra,
  }
}

const VISIT: Visit = {
  id: 'v1',
  started_at: '2026-10-02T03:00:00Z',
  ended_at: '2026-10-02T03:03:20Z',
  state: 'completed',
  end_reason: null,
  profile_id: 'p1',
  profile_name: 'Garden Party',
  layout: 'strip_2x6',
  photos: 6,
  retakes: 1,
  failed_attempts: 0,
  outputs: 2,
  filter: 'sepia',
  stickers: 2,
  link_issued: true,
  link_opened: true,
  downloads: 3,
}

const STATS: Statistics = {
  since: null,
  until: null,
  visits: 12,
  finished: 9,
  cancelled: 1,
  abandoned: 1,
  errors: 1,
  in_progress: 0,
  photos: 60,
  retakes: 4,
  failed_attempts: 0,
  outputs: 14,
  decorated: 6,
  links_opened: 7,
  downloads: 11,
  average_minutes: 3.4,
  by_layout: [
    { key: 'strip_2x6', count: 8 },
    { key: 'print_4x6', count: 4 },
  ],
  by_hour: [
    { key: '18', count: 5 },
    { key: '19', count: 7 },
  ],
  by_filter: [
    { key: 'none', count: 3 },
    { key: 'sepia', count: 6 },
  ],
}

describe('History', () => {
  it('lists visits in plain words and opens one with what happened', async () => {
    const server = signedIn()
    server.historyPage = { visits: [VISIT], total: 1, offset: 0 }
    const detail: VisitDetail = {
      visit: VISIT,
      timeline: [
        record('a', 'session_started'),
        record('b', 'frame_chosen', { payload: { layout: 'strip_2x6', captures: 6, outputs: 2 } }),
        record('c', 'capture_ok', { payload: { shot: 2, attempt: 2 } }),
        record('d', 'render_ok', { payload: { outputs: 2, filter: 'sepia', stickers: 2 } }),
        record('e', 'download', { actor: 'guest', payload: { kind: 'zip' } }),
        record('f', 'session_ended', { payload: { state: 'completed', reason: 'done' } }),
      ],
    }
    server.visits.set('v1', detail)
    renderAdmin('/admin/history', { server })
    const table = await screen.findByTestId('history-table')
    const row = within(table).getAllByRole('row')[1] as HTMLElement
    for (const text of ['Garden Party', '2×6', 'Finished', '6 (+1 retaken)', 'Sepia, 2 stickers']) {
      expect(within(row).getByText(text)).toBeInTheDocument()
    }
    expect(within(row).getByText('Opened · 3↓')).toBeInTheDocument()
    expect(within(row).getByText('3 min 20 s')).toBeInTheDocument()

    await userEvent.click(within(row).getByRole('button', { name: 'Details' }))
    const dialog = await screen.findByTestId('visit-dialog')
    const timeline = await within(dialog).findByTestId('visit-timeline')
    expect(within(timeline).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      expect.stringContaining('A guest started a visit'),
      expect.stringContaining('Chose a 2×6 frame (6 photos)'),
      expect.stringContaining('Photo 2 taken again (try 2)'),
      expect.stringContaining('Finished photos made with Sepia and 2 stickers'),
      expect.stringContaining('Downloaded all photos (ZIP)'),
      expect.stringContaining('Visit ended: Finished'),
    ])
    expect(within(timeline).getAllByText('Guest phone')).toHaveLength(1)
  })

  it('asks the server for the chosen period, result and page', async () => {
    const server = signedIn()
    server.historyPage = {
      visits: Array.from({ length: 25 }, (_, n) => ({ ...VISIT, id: `v${n}` })),
      total: 40,
      offset: 0,
    }
    renderAdmin('/admin/history', { server })
    await screen.findByTestId('history-table')
    const asked = () => server.requests.filter((r) => r.path.startsWith('/api/admin/history'))
    expect(asked().at(-1)?.path).toMatch(/since=.*limit=25/)

    await userEvent.click(screen.getByRole('button', { name: 'Ended early' }))
    await waitFor(() =>
      expect(asked().at(-1)?.path).toContain('state=cancelled&state=abandoned&state=error'),
    )
    await userEvent.click(screen.getByRole('button', { name: 'All time' }))
    await waitFor(() => expect(asked().at(-1)?.path).not.toContain('since='))
    await userEvent.click(await screen.findByRole('button', { name: 'Older' }))
    await waitFor(() => expect(asked().at(-1)?.path).toContain('offset=25'))
  })

  it('says so when there are no visits', async () => {
    renderAdmin('/admin/history', { server: signedIn() })
    expect(await screen.findByText('No visits in this period.')).toBeInTheDocument()
  })
})

describe('Statistics', () => {
  it('shows the headline numbers and writes every chart value out', async () => {
    const server = signedIn()
    server.statistics = STATS
    renderAdmin('/admin/statistics', { server })
    const tiles = await screen.findByTestId('statistics-tiles')
    expect(within(tiles).getByText('Visits').nextSibling).toHaveTextContent('12')
    expect(within(tiles).getByText('75% of visits')).toBeInTheDocument()
    expect(within(tiles).getByText('3.4 min')).toBeInTheDocument()
    expect(within(tiles).getByText('1 left · 1 timed out · 1 errors')).toBeInTheDocument()

    const layouts = screen.getByRole('region', { name: 'Visits by layout' })
    expect(within(layouts).getByText('2×6')).toBeInTheDocument()
    expect(within(layouts).getByText('8')).toBeInTheDocument()
    const filters = screen.getByRole('region', { name: 'Filters on finished photos' })
    expect(within(filters).getByText('Sepia')).toBeInTheDocument()
    expect(within(filters).getByText('no filter')).toBeInTheDocument()
    // The hourly chart has a table behind it for anyone who can not see the bars.
    const hours = screen.getByRole('table', { name: 'Visits started in each hour' })
    expect(within(hours).getAllByRole('row').map((r) => r.textContent)).toEqual([
      'HourVisits',
      '18:005',
      '19:007',
    ])
  })

  it('asks again for another period', async () => {
    const server = signedIn()
    server.statistics = STATS
    renderAdmin('/admin/statistics', { server })
    await screen.findByTestId('statistics-tiles')
    await userEvent.click(screen.getByRole('button', { name: 'Last 7 days' }))
    await waitFor(() =>
      expect(
        server.requests.filter((r) => r.path.startsWith('/api/admin/statistics')),
      ).toHaveLength(2),
    )
  })
})

describe('Activity log', () => {
  it('shows who did what, newest first, and pages back in time', async () => {
    const server = signedIn()
    server.activityPages = [
      {
        records: [
          record('1', 'admin_profile_activated', {
            actor: 'admin',
            admin_username: 'admin',
            session_id: null,
            payload: { target: 'p1' },
          }),
          record('2', 'qr_opened', { actor: 'guest' }),
        ],
        more: true,
      },
      { records: [record('3', 'admin_login_failed', { actor: 'admin' })], more: false },
    ]
    renderAdmin('/admin/activity', { server })
    const log = await screen.findByTestId('activity-log')
    expect(within(log).getByText('Made an event profile live')).toBeInTheDocument()
    expect(within(log).getByText('admin')).toBeInTheDocument()
    expect(within(log).getByText('A phone opened the take-home link')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Show older' }))
    expect(
      await within(log).findByText('Sign-in refused: wrong user name or password'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show older' })).not.toBeInTheDocument()
    const older = server.requests.filter((r) => r.path.startsWith('/api/admin/activity')).at(-1)
    expect(older?.path).toContain('before_id=2')

    await userEvent.click(screen.getByRole('button', { name: 'Organizers' }))
    await waitFor(() =>
      expect(
        server.requests.filter((r) => r.path.startsWith('/api/admin/activity')).at(-1)?.path,
      ).toContain('actor=admin'),
    )
  })

  it('needs an organizer', async () => {
    renderAdmin('/admin/activity')
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument()
  })
})
