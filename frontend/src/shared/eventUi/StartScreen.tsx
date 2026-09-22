import { useState } from 'react'

import type { ThemeTokens } from '../eventTheme/theme'
import { EventButton, EventScreen } from './EventUi'
import styles from './StartScreen.module.css'

interface StartScreenProps {
  tokens: ThemeTokens
  backgroundImageUrl?: string | null
  logoUrl?: string | null
  /** The profile's Start button text; "Start" when empty. */
  startText: string
  onStart?: () => void
  label?: string
  /** Previews: the button is shown but not in the Tab order. */
  inert?: boolean
}

/** The neutral Photobooth mark, used when the event has no logo (or it can not be loaded). */
function DefaultMark() {
  return (
    <svg
      className={styles.mark}
      viewBox="0 0 120 120"
      role="img"
      aria-label="Photobooth"
      fill="none"
      stroke="currentColor"
      strokeWidth={6}
      strokeLinejoin="round"
    >
      <circle cx="60" cy="60" r="54" />
      <path d="M34 46h14l6-9h12l6 9h14v36H34z" />
      <circle cx="60" cy="64" r="11" />
    </svg>
  )
}

/**
 * The participant start screen: the event background, one centred logo and one large Start
 * button. Nothing else belongs here (no text fields, messages or examples).
 */
export function StartScreen({
  tokens,
  backgroundImageUrl,
  logoUrl,
  startText,
  onStart,
  label = 'Start screen',
  inert = false,
}: StartScreenProps) {
  const [failedLogo, setFailedLogo] = useState<string | null>(null)
  const showLogo = Boolean(logoUrl) && failedLogo !== logoUrl
  return (
    <EventScreen
      tokens={tokens}
      backgroundImageUrl={backgroundImageUrl ?? null}
      className={styles.start}
      label={label}
    >
      <div className={styles.center} data-testid="start-screen">
        {showLogo && logoUrl ? (
          <img
            src={logoUrl}
            alt="Event logo"
            className={styles.logo}
            onError={() => setFailedLogo(logoUrl)}
          />
        ) : (
          <DefaultMark />
        )}
        <EventButton
          variant="primary"
          className={styles.startButton}
          onClick={onStart}
          {...(inert ? { tabIndex: -1 } : {})}
        >
          {startText.trim() || 'Start'}
        </EventButton>
      </div>
    </EventScreen>
  )
}
