import type { ReactNode } from 'react'

import { useEnterImmersive } from '../../shared/ui/immersive'
import styles from './BoothShell.module.css'

/**
 * The booth's own display.
 *
 * Every participant screen sits in this one shell, whether a guest opened `/booth` or an
 * organizer started a test from Admin: it takes the whole viewport (the whole display when the
 * browser grants fullscreen), keeps the page from scrolling, respects the device's safe areas,
 * and puts nothing of the surrounding app on screen. There is no second booth layout.
 */
export function BoothShell({ children }: { children: ReactNode }) {
  useEnterImmersive()
  return (
    <div className={styles.shell} data-testid="booth-shell">
      {children}
    </div>
  )
}
