import type { RetentionPolicyBody } from '../../shared/api/adminClient'

/**
 * Retention policies in words a person can read (the Retention page and the profile editor).
 */

const RECORDS: Record<RetentionPolicyBody['metadata_mode'], string> = {
  keep: 'records kept',
  anonymize: 'records made anonymous',
  delete: 'records deleted',
}

function days(count: number): string {
  return `${count} day${count === 1 ? '' : 's'}`
}

/** What this policy keeps, and for how long, in one line. */
export function policySummary(policy: RetentionPolicyBody): string {
  const records =
    policy.metadata_mode === 'keep'
      ? 'visit records kept'
      : `${RECORDS[policy.metadata_mode]} after ${days(policy.metadata_days)}`
  return `Original photos ${days(policy.originals_days)} · finished photos ${days(policy.outputs_days)} · link ${days(policy.link_days)} · ${records}`
}
