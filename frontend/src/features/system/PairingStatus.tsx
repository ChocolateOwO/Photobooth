import { useKioskStatus } from './useSystemStatus'

export function PairingStatus() {
  const { data, isPending, isError } = useKioskStatus()
  let text: string
  if (isPending) {
    text = 'Checking kiosk pairing…'
  } else if (isError) {
    text = 'Kiosk pairing unknown'
  } else if (data.paired) {
    text = 'Kiosk paired'
  } else {
    text = 'Kiosk not paired (open the booth with scripts\\run-dummy.ps1)'
  }
  return <p data-testid="pairing-status">{text}</p>
}
