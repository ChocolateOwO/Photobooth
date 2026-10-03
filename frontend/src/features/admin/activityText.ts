import type { ActivityRecord, Visit } from '../../shared/api/adminClient'

/**
 * Activity records and visits in plain words for organizers. The server keeps only allowlisted
 * facts (no token, path, IP or free text), so everything shown here is safe to show.
 */

type Payload = ActivityRecord['payload']

function num(payload: Payload, key: string): number | undefined {
  const value = payload[key]
  return typeof value === 'number' ? value : undefined
}

function word(payload: Payload, key: string): string | undefined {
  const value = payload[key]
  return typeof value === 'string' ? value : undefined
}

const FILTER_NAMES: Record<string, string> = {
  none: 'no filter',
  mono: 'Black & white',
  sepia: 'Sepia',
  warm: 'Warm',
  cool: 'Cool',
  bright: 'Bright',
}

export function filterName(key: string | null | undefined): string {
  if (!key) return 'no filter'
  return FILTER_NAMES[key] ?? key
}

const LAYOUT_NAMES: Record<string, string> = {
  strip_2x6: '2×6',
  print_3x4: '3×4',
  print_4x6: '4×6',
}

/** A layout as organizers know it ("2×6"), from the template key the server records. */
export function layoutName(key: string | null | undefined): string {
  if (!key) return '—'
  return LAYOUT_NAMES[key] ?? key
}

const STATE_NAMES: Record<string, string> = {
  eligibility_ok: 'Choosing a frame',
  capturing: 'Taking photos',
  reviewing: 'Decorating',
  delivered: 'Photos ready',
  completed: 'Finished',
  cancelled: 'Left early',
  abandoned: 'Timed out',
  error: 'Error',
}

export function stateName(state: string): string {
  return STATE_NAMES[state] ?? state
}

const END_REASONS: Record<string, string> = {
  inactivity: 'nobody at the booth',
  next_guest: 'the next guest started',
  photo_missing: 'a photo was missing',
  frame_changed: 'the frame changed',
  frame_missing: 'the frame was missing',
  template_missing: 'the layout was missing',
  render_failed: 'the photos could not be made',
  decoration_missing: 'a sticker was missing',
}

export function endReason(code: string | null | undefined): string | null {
  if (!code) return null
  return END_REASONS[code] ?? code
}

/** One activity record as a sentence. */
export function describe(record: ActivityRecord): string {
  const p = record.payload
  const target = word(p, 'target')
  switch (record.type) {
    case 'session_started':
      return 'A guest started a visit'
    case 'frame_chosen': {
      const layout = word(p, 'layout') ? layoutName(word(p, 'layout')) : undefined
      const photos = num(p, 'captures')
      return `Chose ${layout ? `a ${layout}` : 'a'} frame${photos ? ` (${photos} photos)` : ''}`
    }
    case 'capture_ok':
      return (num(p, 'attempt') ?? 1) > 1
        ? `Photo ${num(p, 'shot') ?? '?'} taken again (try ${num(p, 'attempt')})`
        : `Photo ${num(p, 'shot') ?? '?'} taken`
    case 'capture_failed':
      return `Photo ${num(p, 'shot') ?? '?'} could not be kept`
    case 'retake':
      return num(p, 'shots') === 1 ? 'Asked to retake a photo' : 'Asked to retake the photos'
    case 'photos_confirmed':
      return `Confirmed ${num(p, 'photos') ?? 'the'} photos`
    case 'render_ok': {
      const stickers = num(p, 'stickers') ?? 0
      const decorated = [
        word(p, 'filter') && word(p, 'filter') !== 'none' ? filterName(word(p, 'filter')) : null,
        stickers ? `${stickers} sticker${stickers === 1 ? '' : 's'}` : null,
      ].filter(Boolean)
      const outputs = num(p, 'outputs') ?? 1
      return `Finished photo${outputs === 1 ? '' : 's'} made${
        decorated.length ? ` with ${decorated.join(' and ')}` : ''
      }`
    }
    case 'render_failed':
      return `Finished photos could not be made (${endReason(word(p, 'reason')) ?? 'error'})`
    case 'link_shown':
      return p.renewed === true ? 'Showed a new take-home QR code' : 'Showed the take-home QR code'
    case 'session_ended':
      return `Visit ended: ${stateName(word(p, 'state') ?? '')}${
        endReason(word(p, 'reason')) ? ` (${endReason(word(p, 'reason'))})` : ''
      }`
    case 'reset_timeout':
      return 'Visit ended: nobody at the booth'
    case 'qr_opened':
      return 'A phone opened the take-home link'
    case 'download':
      return word(p, 'kind') === 'zip'
        ? 'Downloaded all photos (ZIP)'
        : `Saved photo ${num(p, 'output') ?? ''}`.trim()
    case 'admin_login':
      return 'Signed in'
    case 'admin_login_failed':
      return word(p, 'reason') === 'throttled'
        ? 'Sign-in refused: too many attempts'
        : 'Sign-in refused: wrong user name or password'
    case 'admin_logout':
      return 'Signed out'
    case 'admin_profile_created':
      return 'Created an event profile'
    case 'admin_profile_updated':
      return 'Changed an event profile'
    case 'admin_profile_duplicated':
      return 'Duplicated an event profile'
    case 'admin_profile_activated':
      return 'Made an event profile live'
    case 'admin_profile_deleted':
      return 'Deleted an event profile'
    case 'admin_profile_restored':
      return 'Restored an event profile'
    case 'admin_frame_uploaded':
      return 'Uploaded a frame'
    case 'admin_frame_replaced':
      return 'Replaced a frame file'
    case 'admin_frame_renamed':
      return 'Renamed a frame'
    case 'admin_frame_deleted':
      return 'Deleted a frame'
    case 'admin_asset_uploaded':
      return 'Uploaded a logo or background'
    case 'admin_asset_deleted':
      return 'Deleted a logo or background'
    case 'admin_test_started':
      return 'Started a booth test'
    case 'admin_tests_cleared':
      return 'Cleared booth tests'
    case 'admin_policy_created':
      return 'Added a retention policy'
    case 'admin_policy_updated':
      return 'Changed a retention policy (for visits from then on)'
    case 'admin_policy_made_default':
      return 'Made a retention policy the default for new profiles'
    case 'admin_policy_deleted':
      return 'Deleted a retention policy'
    case 'admin_profile_policy_chosen':
      return 'Chose the retention policy of an event profile'
    default:
      return target ? `${record.type} (${target})` : record.type
  }
}

const ACTOR_NAMES: Record<string, string> = {
  booth: 'Booth',
  guest: 'Guest phone',
  admin: 'Organizer',
  system: 'System',
}

export function actorName(record: ActivityRecord): string {
  if (record.actor === 'admin' && record.admin_username) return record.admin_username
  return ACTOR_NAMES[record.actor] ?? record.actor
}

/** "3 min 20 s" from start to end, or null while the visit is still going. */
export function duration(visit: Pick<Visit, 'started_at' | 'ended_at'>): string | null {
  if (!visit.ended_at) return null
  const seconds = Math.max(
    0,
    Math.round((Date.parse(visit.ended_at) - Date.parse(visit.started_at)) / 1000),
  )
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  if (hours) return `${hours} h ${minutes % 60} min`
  return minutes ? `${minutes} min ${seconds % 60} s` : `${seconds} s`
}

/** The booth speaks English, whatever language the machine is set to. */
export function when(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
