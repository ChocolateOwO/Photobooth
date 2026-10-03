import { describe, expect, it } from 'vitest'

import type { ActivityRecord } from '../../shared/api/adminClient'
import { describe as say, duration, endReason, layoutName, stateName } from './activityText'
import { periodRange } from './period'

function record(type: string, payload: ActivityRecord['payload'] = {}): ActivityRecord {
  return {
    id: 'x',
    at: '2026-10-02T00:00:00Z',
    type,
    actor: 'booth',
    session_id: null,
    profile_id: null,
    admin_username: null,
    payload,
  }
}

describe('activity in plain words', () => {
  it('says what happened', () => {
    expect(say(record('capture_ok', { shot: 3, attempt: 1 }))).toBe('Photo 3 taken')
    expect(say(record('render_ok', { outputs: 1, filter: 'none', stickers: 0 }))).toBe(
      'Finished photo made',
    )
    expect(say(record('render_ok', { outputs: 2, filter: 'mono', stickers: 1 }))).toBe(
      'Finished photos made with Black & white and 1 sticker',
    )
    expect(say(record('download', { kind: 'file', output: 2 }))).toBe('Saved photo 2')
    expect(say(record('reset_timeout', { state: 'abandoned' }))).toBe(
      'Visit ended: nobody at the booth',
    )
    expect(say(record('admin_login_failed', { reason: 'throttled' }))).toBe(
      'Sign-in refused: too many attempts',
    )
    expect(say(record('link_shown', { renewed: true }))).toBe('Showed a new take-home QR code')
    expect(say(record('link_shown', { renewed: false }))).toBe('Showed the take-home QR code')
    expect(say(record('something_new'))).toBe('something_new')
  })

  it('tells retention policy changes and a profile choosing one, without names (P11-9)', () => {
    const policy = '00000000-0000-4000-8000-000000000001'
    expect(say(record('admin_policy_created', { target: policy }))).toBe('Added a retention policy')
    expect(say(record('admin_policy_updated', { target: policy }))).toBe(
      'Changed a retention policy (for visits from then on)',
    )
    expect(say(record('admin_policy_made_default', { target: policy }))).toBe(
      'Made a retention policy the default for new profiles',
    )
    expect(say(record('admin_policy_deleted', { target: policy }))).toBe(
      'Deleted a retention policy',
    )
    expect(say(record('admin_profile_policy_chosen', { policy }))).toBe(
      'Chose the retention policy of an event profile',
    )
  })

  it('names states, reasons and layouts', () => {
    expect(stateName('abandoned')).toBe('Timed out')
    expect(endReason('next_guest')).toBe('the next guest started')
    expect(endReason(null)).toBeNull()
    expect(layoutName('print_3x4')).toBe('3×4')
    expect(layoutName(null)).toBe('—')
  })

  it('measures a visit, or says it is still going', () => {
    expect(duration({ started_at: '2026-10-02T00:00:00Z', ended_at: '2026-10-02T00:00:42Z' })).toBe(
      '42 s',
    )
    expect(duration({ started_at: '2026-10-02T00:00:00Z', ended_at: '2026-10-02T04:20:44Z' })).toBe(
      '4 h 20 min',
    )
    expect(duration({ started_at: '2026-10-02T00:00:00Z', ended_at: null })).toBeNull()
  })
})

describe('periods on the booth clock', () => {
  const now = new Date(2026, 9, 2, 15, 30) // 2 October, 15:30 local time

  it('starts today at local midnight and yesterday a calendar day before', () => {
    expect(periodRange('today', now)).toEqual({ since: new Date(2026, 9, 2).toISOString() })
    expect(periodRange('yesterday', now)).toEqual({
      since: new Date(2026, 9, 1).toISOString(),
      until: new Date(2026, 9, 2).toISOString(),
    })
    expect(periodRange('week', now)).toEqual({ since: new Date(2026, 8, 26).toISOString() })
    expect(periodRange('all', now)).toEqual({})
  })
})
