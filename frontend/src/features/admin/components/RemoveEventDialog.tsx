import { useEffect, useState } from 'react'

import { AdminApiError, type EventProfile } from '../../../shared/api/adminClient'
import { useRemoveEvent } from '../api/hooks'
import { PillButton } from './ui/Controls'
import { Modal } from './ui/Modal'

/**
 * Deleting a deleted event for good: the event and every visit of it (photos, finished photos,
 * links, records) go, permanently. It first counts what would go, says so, and only a ticked box
 * lets it go ahead. An event with a visit still going is refused by the server.
 */
export function RemoveEventDialog({
  profile,
  onClose,
}: {
  profile: EventProfile
  onClose: () => void
}) {
  const check = useRemoveEvent()
  const remove = useRemoveEvent()
  const [understood, setUnderstood] = useState(false)
  const { mutate } = check
  useEffect(() => {
    mutate({ id: profile.id, dryRun: true })
  }, [mutate, profile.id])

  const error = check.error ?? remove.error
  const problem =
    error instanceof AdminApiError ? error.messages.join(' ') : error ? 'That did not work.' : null
  const visits = check.data?.visits

  return (
    <Modal
      title={`Delete ${profile.settings.name} for good?`}
      tone="warning"
      onClose={onClose}
      testId="remove-event"
      footer={
        <>
          <PillButton onClick={onClose}>Keep it</PillButton>
          <PillButton
            tone="danger"
            disabled={!understood || visits === undefined || remove.isPending}
            onClick={() =>
              remove.mutate({ id: profile.id, dryRun: false }, { onSuccess: () => onClose() })
            }
          >
            Delete for good
          </PillButton>
        </>
      }
    >
      {check.isPending && <p>Counting what would go…</p>}
      {visits !== undefined && (
        <p>
          The event and its {visits} visit{visits === 1 ? '' : 's'} (photos, finished photos,
          take-home links and records) are deleted permanently. This can not be undone.
        </p>
      )}
      {problem && <p role="alert">{problem}</p>}
      <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <input
          type="checkbox"
          checked={understood}
          onChange={(event) => setUnderstood(event.target.checked)}
        />
        I understand this can not be brought back.
      </label>
    </Modal>
  )
}
