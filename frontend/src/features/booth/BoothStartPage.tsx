
import { StartScreen } from '../../shared/eventUi/StartScreen'
import { BoothLoadState } from './BoothLoadState'
import { BoothShell } from './BoothShell'
import { useBoothMenu } from './boothMenu'
import { useBoothServices } from './boothServices'
import styles from './BoothStartPage.module.css'

/**
 * The real participant start screen (/booth): the same StartScreen component the admin preview
 * draws, fed by the participant API. Start goes to the frame choice; capture is a later phase.
 */
export function BoothStartPage() {
  const menu = useBoothMenu()
  const booth = useBoothServices()

  if (menu.isPending) {
    return (
      <BoothShell>
        <p className={styles.loading}>Loading…</p>
      </BoothShell>
    )
  }
  if (menu.isError) {
    return (
      <BoothShell>
        <BoothLoadState error={menu.error} onRetry={() => void menu.refetch()} />
      </BoothShell>
    )
  }

  const screen = menu.data.start_screen
  return (
    <BoothShell>
      <StartScreen
        tokens={menu.data.theme}
        backgroundImageUrl={screen.background_url}
        logoUrl={screen.logo_url}
        startText={screen.start_button_text}
        onStart={() => booth.go('frames')}
      />
    </BoothShell>
  )
}
